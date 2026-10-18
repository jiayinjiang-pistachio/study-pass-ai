<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { Delete } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import '@wangeditor-next/editor/dist/css/style.css'
import { Editor, Toolbar } from '@wangeditor-next/editor-for-vue'
import type { IDomEditor, IEditorConfig, IToolbarConfig } from '@wangeditor-next/editor'
import { useNoteStore } from '@/stores/note'

/** 内容自动保存防抖时长 */
const SAVE_DELAY = 600

const noteStore = useNoteStore()
const { notes, activeNoteId } = storeToRefs(noteStore)

const editorRef = shallowRef<IDomEditor>()
const valueHtml = ref('')
const title = ref('')

const toolbarConfig: Partial<IToolbarConfig> = {
  toolbarKeys: [
    'bold',
    'italic',
    'underline',
    'bulletedList',
    'numberedList',
    'indent',
    'delIndent',
    '|',
    'insertLink',
    'insertImage',
  ],
}

const editorConfig: Partial<IEditorConfig> = {
  placeholder: '开始记录你的学习笔记…',
}

const activeNote = computed(() => notes.value.find((item) => item.id === activeNoteId.value))

let saveTimer: ReturnType<typeof setTimeout> | undefined

function clearSaveTimer(): void {
  if (saveTimer) {
    clearTimeout(saveTimer)
    saveTimer = undefined
  }
}

function handleCreated(editor: IDomEditor): void {
  editorRef.value = editor
}

function scheduleSave(html: string): void {
  const id = activeNoteId.value
  if (!id) return
  clearSaveTimer()
  saveTimer = setTimeout(() => {
    saveTimer = undefined
    void noteStore.saveContent(id, html)
  }, SAVE_DELAY)
}

function saveTitle(): void {
  const note = activeNote.value
  if (!note) return
  const trimmed = title.value.trim()
  if (!trimmed) {
    title.value = note.title
    return
  }
  if (trimmed === note.title) return
  void noteStore.rename(note.id, trimmed)
}

async function handleDelete(): Promise<void> {
  const note = activeNote.value
  if (!note) return
  try {
    await ElMessageBox.confirm(`确定删除笔记「${note.title}」吗？`, '删除确认', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await noteStore.remove(note.id)
    ElMessage.success('已删除')
  } catch {
    /* 用户取消，无需处理 */
  }
}

// 切换笔记：清掉待保存的定时器，并把内容/标题同步到当前笔记
watch(
  activeNoteId,
  () => {
    clearSaveTimer()
    valueHtml.value = activeNote.value?.content ?? ''
    title.value = activeNote.value?.title ?? ''
  },
  { immediate: true },
)

// 编辑内容变化 → 防抖保存
watch(valueHtml, (html) => scheduleSave(html))

onMounted(() => {
  if (!notes.value.length) void noteStore.load()
})

onBeforeUnmount(() => {
  clearSaveTimer()
  editorRef.value?.destroy()
})
</script>

<template>
  <div class="note-room">
    <div class="note-room__card">
      <div class="note-room__toolbar">
        <Toolbar
          class="note-room__toolbar-bar"
          :editor="editorRef"
          :default-config="toolbarConfig"
          mode="default"
        />
        <button type="button" class="note-room__delete" title="删除笔记" @click="handleDelete">
          <el-icon><Delete /></el-icon>
        </button>
      </div>

      <input
        v-model="title"
        class="note-room__title"
        type="text"
        placeholder="笔记标题"
        @keydown.enter.prevent="saveTitle"
        @blur="saveTitle"
      />

      <div class="note-room__body">
        <Editor
          v-model="valueHtml"
          class="note-room__editor"
          :default-config="editorConfig"
          mode="default"
          @onCreated="handleCreated"
        />
      </div>
    </div>
  </div>
</template>

<style lang="scss" scoped>
.note-room {
  flex: 1;
  min-height: 0;
  display: flex;
  justify-content: center;
  padding: 28px 24px;
  overflow: hidden;

  &__card {
    display: flex;
    flex-direction: column;
    width: 100%;
    max-width: var(--editor-max-width);
    min-height: 0;
    background: var(--color-surface);
    border-radius: 12px;
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
    overflow: hidden;
  }

  &__toolbar {
    flex: none;
    display: flex;
    align-items: center;
    border-bottom: 1px solid var(--color-divider);
  }

  &__toolbar-bar {
    flex: 1;
    min-width: 0;
  }

  &__delete {
    flex: none;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 40px;
    height: 40px;
    border: none;
    background: transparent;
    color: var(--color-text-muted);
    font-size: 18px;
    cursor: pointer;
    transition: color 0.2s;

    &:hover {
      color: var(--color-text);
    }
  }

  &__title {
    flex: none;
    width: 100%;
    padding: 20px 24px 14px;
    border: none;
    border-bottom: 1px solid var(--color-divider);
    outline: none;
    background: transparent;
    font-family: inherit;
    font-size: 20px;
    font-weight: 700;
    color: var(--color-text);

    &::placeholder {
      font-weight: 400;
      color: var(--color-text-muted);
    }
  }

  &__body {
    flex: 1;
    min-height: 0;
  }

  /* 让编辑区在卡片内撑满并独立滚动 */
  &__body :deep(.w-e-text-container) {
    height: 100%;
  }

  &__body :deep(.w-e-scroll) {
    height: 100%;
    overflow-y: auto;
  }
}
</style>
