import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'
import type { Note, NoteSummary } from '@/types/note'
import * as noteApi from '@/api/notes'
import { renderMarkdown } from '@/utils/markdownUtil'

const PAGE_SIZE = 100
const SAVE_DELAY = 600
const DEFAULT_TITLE = '无标题笔记'
const EMPTY_CONTENT = '<p><br></p>'

/** 常见富文本根标签；命中即认为后端存的已经是 HTML */
const HTML_TAG_RE =
  /^\s*<(?:p|div|h[1-6]|ul|ol|li|table|thead|tbody|tr|td|th|blockquote|pre|code|img|figure|section|article|span|strong|em|u|s|br|hr|a)\b/i

function toEditorHtml(content: string): string {
  if (!content) return EMPTY_CONTENT
  if (HTML_TAG_RE.test(content)) return content
  // renderMarkdown 自带 .md-content 根节点，富文本编辑器不需要这层包装
  return renderMarkdown(content)
    .replace(/^<div class="md-content">/, '')
    .replace(/<\/div>\s*$/, '')
}

export const useNoteStore = defineStore('note', () => {
  const noteList = ref<NoteSummary[]>([])
  const activeNoteId = ref<number | null>(null)
  const activeNote = ref<Note | null>(null)
  const loading = ref(false)
  const saving = ref(false)
  const loaded = ref(false)

  /** 编辑器中的草稿；保存后与 savedContent / savedTitle 对齐 */
  const draftTitle = ref('')
  const draftContent = ref('')
  const savedTitle = ref('')
  const savedContent = ref('')

  const dirty = computed(
    () =>
      activeNote.value !== null &&
      (draftTitle.value !== savedTitle.value || draftContent.value !== savedContent.value),
  )

  let noteSessionId: number | null = null
  let saveTimer: ReturnType<typeof setTimeout> | undefined
  let savingPromise: Promise<void> | null = null
  let loadToken = 0

  function clearSaveTimer(): void {
    if (saveTimer) {
      clearTimeout(saveTimer)
      saveTimer = undefined
    }
  }

  function patchSummary(note: NoteSummary): void {
    const target = noteList.value.find((item) => item.id === note.id)
    if (target) Object.assign(target, note)
  }

  function hydrate(note: Note): void {
    const html = toEditorHtml(note.content)
    activeNote.value = note
    savedTitle.value = note.title
    savedContent.value = html
    draftTitle.value = note.title
    draftContent.value = html
  }

  function clearActive(): void {
    loadToken += 1
    activeNote.value = null
    savedTitle.value = ''
    savedContent.value = ''
    draftTitle.value = ''
    draftContent.value = ''
  }

  async function loadActive(): Promise<void> {
    const id = activeNoteId.value
    if (id === null) {
      clearActive()
      return
    }
    const token = ++loadToken
    const note = await noteApi.getNote(id)
    // 快速切换时丢弃过期响应，避免旧笔记覆盖当前编辑器
    if (token !== loadToken || activeNoteId.value !== id) return
    hydrate(note)
  }

  async function load(): Promise<void> {
    if (loading.value) return
    loading.value = true
    try {
      const result = await noteApi.listNotes({ page: 1, pageSize: PAGE_SIZE })
      noteList.value = result.items
      loaded.value = true

      const stillExists =
        activeNoteId.value !== null &&
        result.items.some((item) => item.id === activeNoteId.value)
      if (!stillExists) {
        activeNoteId.value = result.items[0]?.id ?? null
      }
      await loadActive()
    } finally {
      loading.value = false
    }
  }

  async function ensureLoaded(): Promise<void> {
    if (loaded.value || loading.value) return
    await load()
  }

  function scheduleAutoSave(): void {
    if (!dirty.value) return
    clearSaveTimer()
    saveTimer = setTimeout(() => {
      saveTimer = undefined
      void saveActiveNote({ silent: true }).catch(() => {
        /* 自动保存失败保持草稿，下次修改或手动保存时重试 */
      })
    }, SAVE_DELAY)
  }

  /** 保存当前笔记；标题为空时回退到原标题 */
  async function saveActiveNote(options: { silent?: boolean } = {}): Promise<void> {
    clearSaveTimer()
    // 串行化保存：切换 / 手动保存要等上一次请求结束，避免旧内容回写
    if (savingPromise) await savingPromise
    clearSaveTimer()

    const note = activeNote.value
    if (!note) return

    const title = draftTitle.value.trim() || note.title
    const content = draftContent.value || EMPTY_CONTENT
    if (title === savedTitle.value && content === savedContent.value) return

    saving.value = true
    const task = (async () => {
      try {
        const updated = await noteApi.updateNote(
          note.id,
          { title, content },
          { silent: options.silent },
        )
        patchSummary(updated)
        // 保存期间用户继续输入时不要用旧内容覆盖新草稿
        if (activeNote.value?.id !== note.id) return
        savedTitle.value = updated.title
        savedContent.value = content
        if (draftTitle.value === title) draftTitle.value = updated.title
        if (draftContent.value === content) draftContent.value = content
      } finally {
        saving.value = false
        // 保存期间又有新改动，补一次自动保存
        if (dirty.value) scheduleAutoSave()
      }
    })()

    savingPromise = task
    try {
      await task
    } finally {
      if (savingPromise === task) savingPromise = null
    }
  }

  /**
   * 编辑器加载外部内容后会回写一次规范化 HTML。
   * 在用户尚未改动时把它作为保存基线，避免「加载即自动保存」。
   */
  function syncEditorContent(value: string): void {
    if (!activeNote.value) return
    if (draftContent.value !== savedContent.value) return
    savedContent.value = value
    draftContent.value = value
  }

  /** 切换 / 离开前静默保存（不弹确认框，失败仍由请求层提示） */
  async function flushSave(): Promise<void> {
    await saveActiveNote()
  }

  async function select(id: number): Promise<void> {
    if (id === activeNoteId.value) return
    try {
      await flushSave()
    } catch {
      // 保存失败时保持当前笔记，避免丢失修改
      return
    }
    activeNoteId.value = id
    await loadActive()
  }

  async function resolveNoteSession(): Promise<number> {
    if (noteSessionId !== null) return noteSessionId
    noteSessionId = await noteApi.ensureNoteSession()
    return noteSessionId
  }

  async function create(): Promise<void> {
    try {
      await flushSave()
    } catch {
      // 当前笔记保存失败时不再新建，避免掩盖丢失的修改
      return
    }
    const sessionId = await resolveNoteSession()
    const note = await noteApi.createNote({
      sessionId,
      title: DEFAULT_TITLE,
      content: EMPTY_CONTENT,
    })
    noteList.value.unshift(note)
    activeNoteId.value = note.id
    hydrate(note)
    loaded.value = true
  }

  async function rename(id: number, title: string): Promise<void> {
    const trimmed = title.trim()
    if (!trimmed) return
    const updated = await noteApi.updateNote(id, { title: trimmed })
    patchSummary(updated)
    if (activeNote.value?.id === id) {
      activeNote.value = { ...activeNote.value, title: updated.title, updatedAt: updated.updatedAt }
      savedTitle.value = updated.title
      draftTitle.value = updated.title
    }
  }

  async function remove(id: number): Promise<void> {
    clearSaveTimer()
    await noteApi.deleteNote(id)
    const index = noteList.value.findIndex((item) => item.id === id)
    if (index !== -1) noteList.value.splice(index, 1)
    if (activeNoteId.value !== id) return

    // 删除当前笔记后优先选中下一篇，没有则回退上一篇
    const next = noteList.value[index] ?? noteList.value[index - 1] ?? null
    activeNoteId.value = next?.id ?? null
    await loadActive()
  }

  /** 退出 / 切换账号时清空笔记状态，避免展示上一个账号的数据 */
  function reset(): void {
    clearSaveTimer()
    noteList.value = []
    activeNoteId.value = null
    clearActive()
    loading.value = false
    saving.value = false
    loaded.value = false
    noteSessionId = null
  }

  watch([draftTitle, draftContent], scheduleAutoSave)

  return {
    noteList,
    activeNoteId,
    activeNote,
    loading,
    saving,
    loaded,
    dirty,
    draftTitle,
    draftContent,
    load,
    ensureLoaded,
    select,
    create,
    rename,
    remove,
    saveActiveNote,
    syncEditorContent,
    flushSave,
    reset,
  }
})
