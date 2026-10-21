import { ref } from 'vue'
import { defineStore } from 'pinia'
import type { ChatModule, Conversation } from '@/types/conversation'
import * as conversationApi from '@/api/conversation'

const PAGE_SIZE = 20
const CHAT_MODULES: ChatModule[] = ['study', 'interview']

interface ListState {
  items: Conversation[]
  page: number
  total: number
  loading: boolean
  loaded: boolean
}

function emptyState(): ListState {
  return { items: [], page: 0, total: 0, loading: false, loaded: false }
}

export const useConversationStore = defineStore('conversation', () => {
  /** 学习室 / 面试间各自维护一份分页列表 */
  const states = ref<Record<ChatModule, ListState>>({
    study: emptyState(),
    interview: emptyState(),
  })
  /** 每个模块各自记录当前选中的会话 id（模块由路由决定） */
  const activeByModule = ref<Record<ChatModule, number | null>>({
    study: null,
    interview: null,
  })

  function stateOf(module: ChatModule): ListState {
    return states.value[module]
  }

  function listOf(module: ChatModule): Conversation[] {
    return states.value[module].items
  }

  function hasMore(module: ChatModule): boolean {
    const state = states.value[module]
    return state.items.length < state.total
  }

  /** 当前选中项不在列表里时，回退到第一项（删除 / 首次加载后使用） */
  function ensureActive(module: ChatModule): void {
    const state = states.value[module]
    const current = activeByModule.value[module]
    if (current !== null && state.items.some((item) => item.id === current)) {
      return
    }
    activeByModule.value[module] = state.items[0]?.id ?? null
  }

  function mergeById(
    current: Conversation[],
    incoming: Conversation[],
  ): Conversation[] {
    const merged = new Map<number, Conversation>()
    for (const item of [...current, ...incoming]) merged.set(item.id, item)
    return [...merged.values()]
  }

  async function load(module: ChatModule, page = 1): Promise<void> {
    const state = states.value[module]
    if (state.loading) return
    state.loading = true
    try {
      const result = await conversationApi.fetchConversations(
        module,
        page,
        PAGE_SIZE,
      )
      state.items =
        page === 1 ? result.items : mergeById(state.items, result.items)
      state.page = result.page
      state.total = result.total
      state.loaded = true
      ensureActive(module)
    } finally {
      state.loading = false
    }
  }

  async function ensureLoaded(module: ChatModule): Promise<void> {
    const state = states.value[module]
    if (state.loaded || state.loading) return
    await load(module)
  }

  async function loadMore(module: ChatModule): Promise<void> {
    const state = states.value[module]
    if (state.loading || !hasMore(module)) return
    await load(module, state.page + 1)
  }

  async function create(module: ChatModule): Promise<void> {
    const created = await conversationApi.createConversation(module)
    await load(module, 1)
    activeByModule.value[module] = created.id

    // 并发写入等极端情况下新会话可能不在第一页，本地补一条保证可切换
    const state = states.value[module]
    if (!state.items.some((item) => item.id === created.id)) {
      state.items.unshift(created)
      state.total += 1
    }
  }

  function find(id: number): { module: ChatModule; item: Conversation } | null {
    for (const module of CHAT_MODULES) {
      const item = states.value[module].items.find((entry) => entry.id === id)
      if (item) return { module, item }
    }
    return null
  }

  async function rename(id: number, title: string): Promise<void> {
    const trimmed = title.trim()
    if (!trimmed) return
    const updated = await conversationApi.renameConversation(id, trimmed)
    const target = find(id)
    if (target) target.item.title = updated.title
  }

  async function remove(module: ChatModule, id: number): Promise<void> {
    await conversationApi.deleteConversation(id)
    if (activeByModule.value[module] === id) {
      activeByModule.value[module] = null
    }
    // 删除后刷新列表，ensureActive 会切换到新的第一项
    await load(module, 1)
  }

  function select(module: ChatModule, id: number): void {
    activeByModule.value[module] = id
  }

  return {
    states,
    activeByModule,
    stateOf,
    listOf,
    hasMore,
    ensureLoaded,
    load,
    loadMore,
    create,
    rename,
    remove,
    select,
  }
})
