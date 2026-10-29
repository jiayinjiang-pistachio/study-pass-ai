import { ref } from 'vue'
import { defineStore } from 'pinia'
import type { ChatMessage } from '@/types/chat'
import type { QuizAnswer } from '@/types/quiz'
import * as conversationApi from '@/api/conversation'
import { submitLearningQuiz } from '@/api/learningWorkflow'
import { buildEvaluationText, quizRunId } from '@/utils/quiz'

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
  // 同 ID 以本地为准：正在流式生成的消息正文比服务端快照新
  for (const item of [...incoming, ...current]) merged.set(item.id, item)
  return [...merged.values()]
}

function mergeServerWins(
  current: ChatMessage[],
  incoming: ChatMessage[],
): ChatMessage[] {
  const merged = new Map<number, ChatMessage>()
  // 服务端快照是落库后的最终结果（测评题目 / 评分），同 ID 覆盖本地副本
  for (const item of [...current, ...incoming]) merged.set(item.id, item)
  return [...merged.values()]
}

export const useChatStore = defineStore('chat', () => {
  /** sessionId -> 消息分页状态 */
  const states = ref<Record<number, MessageState>>({})
  /** sessionId -> 是否正在等待 AI 流式回复（按会话隔离，避免切会话串状态） */
  const sendingBySession = ref<Record<number, boolean>>({})

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

      // 合并而非覆盖：首屏加载与发送可能并发，不能丢掉本地刚插入的消息
      state.items = sortMessages(mergeById(state.items, latest.items))
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

  /**
   * 用服务端最新一页覆盖本地同 ID 消息（服务端优先）。
   *
   * 用于工作流启动 / 评分后的对账：临时行（负数 ID）由落库消息替代，
   * 已加载的更早页保持不动，避免重复插入。
   */
  async function refresh(sessionId: number): Promise<void> {
    const state = stateOf(sessionId)
    const first = await conversationApi.fetchMessages(sessionId, 1, PAGE_SIZE)
    const lastPage = Math.max(1, Math.ceil(first.total / PAGE_SIZE))
    const latest =
      lastPage === 1
        ? first
        : await conversationApi.fetchMessages(sessionId, lastPage, PAGE_SIZE)

    const local = state.items.filter((item) => item.id > 0)
    state.items = sortMessages(mergeServerWins(local, latest.items))
    // 已加载更早页时保持页码不动，避免 loadOlder 跳过中间页
    if (!state.initialized) state.page = latest.page
    state.total = first.total
    state.initialized = true
  }

  function clear(sessionId: number): void {
    delete states.value[sessionId]
  }

  /** 退出 / 切换账号时清空消息缓存与发送态，避免串用上一个账号的数据 */
  function reset(): void {
    states.value = {}
    sendingBySession.value = {}
  }

  function isSending(sessionId: number): boolean {
    return Boolean(sendingBySession.value[sessionId])
  }

  /**
   * 发送一条消息：统一走总控接口。
   *
   * 本地先插入一条「生成中」消息；聊天分支由 meta/delta/done 增量更新，
   * 工作流分支由 JSON 响应触发会话刷新，用落库消息替换临时行。
   * 失败时标记 status=2 并把错误抛给调用方提示。
   */
  async function sendMessage(
    sessionId: number,
    text: string,
    agentName: string,
  ): Promise<void> {
    const content = text.trim()
    if (!content || sendingBySession.value[sessionId]) return

    const state = stateOf(sessionId)
    const createdAt = Date.now()
    state.items.push({
      id: -createdAt,
      requestId: null,
      requestText: content,
      responseText: '',
      requestSegments: [],
      responseSegments: [],
      sources: [],
      status: 0,
      responsePayload: null,
      interviewId: null,
      createdAt,
    })
    state.total += 1
    // 从响应式数组取回代理，直接修改原始对象不会触发视图更新
    const item = state.items[state.items.length - 1]

    sendingBySession.value[sessionId] = true
    let received = ''
    try {
      const result = await conversationApi.startAgentTask(
        sessionId,
        { text: content, agentName },
        {
          onMeta: (meta) => {
            if (meta.requestId) item.requestId = meta.requestId
            if (meta.messageId <= 0) return
            // 首屏加载可能已拉到同一条消息，移除服务端副本，保留正在流式的本地副本
            const duplicate = state.items.find(
              (entry) => entry !== item && entry.id === meta.messageId,
            )
            if (duplicate) state.items.splice(state.items.indexOf(duplicate), 1)
            item.id = meta.messageId
          },
          onDelta: (delta) => {
            received += delta
            item.responseText = received
          },
          onDone: (done) => {
            // 来源只挂在消息结构上展示，不拼进 responseText
            item.sources = done.sources
          },
        },
      )
      item.status = 1

      if (result.kind === 'workflow') {
        try {
          await refresh(sessionId)
        } catch {
          // 刷新失败保留临时行：测评入口仍可用，下次刷新 / 重进会话自动对账
          item.requestId = `${result.data.runId}:quiz`
          item.responsePayload = result.data.quiz
          item.responseText = '已完成出题，请完成后提交答案。'
        }
      }
    } catch (error) {
      item.status = 2
      throw error
    } finally {
      sendingBySession.value[sessionId] = false
    }
  }

  /**
   * 提交测评作答。
   *
   * 先本地更新目标消息（入口立即消失），再刷新用后端点评文本覆盖；
   * 刷新失败保留本地兜底点评，不向用户抛错。
   */
  async function submitQuiz(
    sessionId: number,
    requestId: string,
    answers: QuizAnswer[],
  ): Promise<void> {
    const runId = quizRunId(requestId)
    if (!runId) throw new Error('测评标识无效，请刷新会话后重试')

    const result = await submitLearningQuiz(runId, answers)

    const state = stateOf(sessionId)
    const target = state.items.find((item) => item.requestId === requestId)
    if (target) {
      target.responseText = buildEvaluationText(result)
      target.responsePayload = null
      target.status = 1
    }

    try {
      await refresh(sessionId)
    } catch {
      // 刷新失败保留本地结果
    }
  }

  return {
    states,
    stateOf,
    loadLatest,
    loadOlder,
    refresh,
    clear,
    reset,
    isSending,
    sendMessage,
    submitQuiz,
  }
})
