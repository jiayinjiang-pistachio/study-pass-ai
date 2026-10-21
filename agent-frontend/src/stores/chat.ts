import { ref } from 'vue'
import { defineStore } from 'pinia'
import type { ChatMessage } from '@/types/chat'
import * as conversationApi from '@/api/conversation'

const PAGE_SIZE = 20

interface MessageState {
  items: ChatMessage[]
  page: number
  total: number
  loading: boolean
  loadingOlder: boolean
  initialized: boolean
}

function emptyState(): MessageState {
  return {
    items: [],
    page: 0,
    total: 0,
    loading: false,
    loadingOlder: false,
    initialized: false,
  }
}

function sortMessages(items: ChatMessage[]): ChatMessage[] {
  return [...items].sort(
    (a, b) => a.createdAt - b.createdAt || a.id - b.id,
  )
}

function mergeById(
  current: ChatMessage[],
  incoming: ChatMessage[],
): ChatMessage[] {
  const merged = new Map<number, ChatMessage>()
  for (const item of [...current, ...incoming]) merged.set(item.id, item)
  return [...merged.values()]
}

export const useChatStore = defineStore('chat', () => {
  /** sessionId -> 消息分页状态 */
  const states = ref<Record<number, MessageState>>({})

  function stateOf(sessionId: number): MessageState {
    if (!states.value[sessionId]) {
      states.value[sessionId] = emptyState()
    }
    return states.value[sessionId]
  }

  /**
   * 首屏展示最新一页：先取第 1 页拿 total，再定位到最后一页。
   * 后端消息按时间正序分页，这样既能看到最新消息，又能继续向上翻旧消息。
   */
  async function loadLatest(sessionId: number): Promise<void> {
    const state = stateOf(sessionId)
    if (state.initialized || state.loading) return

    state.loading = true
    try {
      const first = await conversationApi.fetchMessages(sessionId, 1, PAGE_SIZE)
      const lastPage = Math.max(1, Math.ceil(first.total / PAGE_SIZE))
      const latest =
        lastPage === 1
          ? first
          : await conversationApi.fetchMessages(sessionId, lastPage, PAGE_SIZE)

      state.items = sortMessages(latest.items)
      state.page = latest.page
      state.total = first.total
      state.initialized = true
    } finally {
      state.loading = false
    }
  }

  /** 加载更早一页并前插；返回新增条数，供调用方恢复滚动位置 */
  async function loadOlder(sessionId: number): Promise<number> {
    const state = stateOf(sessionId)
    if (state.loading || state.loadingOlder || state.page <= 1) return 0

    state.loadingOlder = true
    try {
      const result = await conversationApi.fetchMessages(
        sessionId,
        state.page - 1,
        PAGE_SIZE,
      )
      const previousLength = state.items.length
      state.items = sortMessages(mergeById(state.items, result.items))
      state.page = result.page
      state.total = result.total
      return state.items.length - previousLength
    } finally {
      state.loadingOlder = false
    }
  }

  function clear(sessionId: number): void {
    delete states.value[sessionId]
  }

  return { states, stateOf, loadLatest, loadOlder, clear }
})
