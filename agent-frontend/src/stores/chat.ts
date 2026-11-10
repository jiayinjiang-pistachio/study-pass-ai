import { ref } from 'vue'
import { defineStore } from 'pinia'
import {
  AgentActivityStatus,
  type AgentActivityNode,
  type ChatMessage,
  type MessageSegment,
} from '@/types/chat'
import type { QuizAnswer } from '@/types/quiz'
import { AgentName } from '@/types/agent'
import { AgentTaskKind } from '@/api/conversation'
import type {
  AgentStepEvent,
  AgentTaskResult,
  KnowledgeCardData,
} from '@/api/conversation'
import * as conversationApi from '@/api/conversation'
import { submitLearningQuiz } from '@/api/learningWorkflow'
import { buildEvaluationText, quizRunId } from '@/utils/quiz'

const PAGE_SIZE = 20
const KNOWLEDGE_LOADING_HINT = '正在生成知识卡和播客，请稍等…'
/** 普通聊天能力名：由后端总控下发，不需要「执行任务」等待提示 */
const CHAT_AGENT_NAME = 'chat_answer'

export interface SendMessageOptions {
  /**
   * 任务事件回调：页面可在此接管特殊任务（如面试背景确认弹窗）。
   * 返回 true 表示已接管，跳过默认的本地渲染与会话刷新逻辑。
   */
  onTaskResult?: (result: AgentTaskResult) => boolean
}

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
  // 已加载更早页的本地消息先保留，再让服务端快照覆盖同 ID 本地副本
  // （服务端快照是落库后的最终结果，测评题目 / 评分以它为准）
  for (const item of current) merged.set(item.id, item)
  for (const item of incoming) {
    const local = merged.get(item.id)
    // 服务端快照已带落库时间轴；本地实时节点更完整时优先保留，避免对账丢步骤
    if (local?.activity?.length) item.activity = local.activity
    if (local?.errorText) item.errorText = local.errorText
    merged.set(item.id, item)
  }
  return [...merged.values()]
}

/**
 * 用工作流 JSON 结果先渲染知识卡，再等会话刷新用落库消息对账。
 * 消息体只存 resource_id 与当前签名 URL，历史读取时由后端重新续签。
 */
function applyKnowledgeCard(
  item: ChatMessage,
  data: KnowledgeCardData,
): void {
  const segments: MessageSegment[] = [
    {
      type: 'image',
      resourceId: data.imageResourceId,
      name: '知识卡',
      url: data.imageUrl,
    },
  ]
  if (data.audioResourceId !== null) {
    segments.push({
      type: 'audio',
      resourceId: data.audioResourceId,
      name: '语音讲解',
      url: data.audioUrl ?? '',
    })
  }

  item.requestId = `${data.runId}:card`
  item.payloadType = 'knowledge_card'
  item.responseText = data.audioResourceId
    ? `已生成知识卡「${data.title}」，点击查看大图，可收听语音讲解。`
    : `已生成知识卡「${data.title}」，点击查看大图。`
  item.responseSegments = segments
  item.loadingHint = undefined
}

/** 节点唯一键：同一能力的同名节点重复上报时只更新状态 */
function activityKey(node: AgentActivityNode): string {
  return `${node.agent}:${node.node}`
}

/** 按 (agent, node) 合并 step：先更新已有节点，未出现则追加 */
function upsertActivity(item: ChatMessage, step: AgentStepEvent): void {
  const status =
    step.status === 'failed'
      ? AgentActivityStatus.Failed
      : step.status === 'start'
        ? AgentActivityStatus.Running
        : AgentActivityStatus.Done
  const nodes = item.activity ?? []
  const existing = nodes.find(
    (node) => activityKey(node) === `${step.agent}:${step.node}`,
  )
  if (existing) {
    existing.status = status
    if (step.title) existing.title = step.title
    if (step.detail !== null) existing.detail = step.detail
    existing.error = step.error
    return
  }
  nodes.push({
    node: step.node,
    agent: step.agent,
    title: step.title,
    status,
    detail: step.detail,
    error: step.error,
  })
  item.activity = nodes
}

/** 流失败：把仍在运行的节点标为失败，并记录服务端错误文案 */
function failActivity(item: ChatMessage, message: string | null): void {
  for (const node of item.activity ?? []) {
    if (node.status === AgentActivityStatus.Running) {
      node.status = AgentActivityStatus.Failed
      node.error = node.error ?? message
    }
  }
  if (message) item.errorText = message
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
   * 刷新对账会丢弃负数临时行，按 request_id 把本地时间轴挂回落库消息，
   * 避免任务完成后执行过程摘要丢失。
   */
  function attachActivity(
    sessionId: number,
    requestId: string,
    source: ChatMessage,
  ): void {
    const target = stateOf(sessionId).items.find(
      (item) => item.requestId === requestId,
    )
    if (!target || target === source) return
    if (source.activity?.length) target.activity = source.activity
    target.errorText = source.errorText ?? target.errorText ?? null
  }

  /**
   * 本页面生命周期内新生成的测评：只有它们允许自动弹出答题窗。
   * 历史 / 刷新后还原的旧试题可能已过期，强制弹窗只会让用户白填一遍。
   */
  const autoOpenQuizIds = new Set<string>()

  function markQuizAutoOpen(requestId: string): void {
    autoOpenQuizIds.add(requestId)
  }

  /** 每个测评只消费一次自动弹窗资格，避免组件重挂载时重复打扰 */
  function consumeQuizAutoOpen(requestId: string): boolean {
    if (!autoOpenQuizIds.delete(requestId)) return false
    return true
  }

  /**
   * 面试准备没有会话产物消息，时间轴只挂在本地临时行上；确认面试时后端用
   * `{run_id}:interview` 新建入口消息，refresh 丢弃临时行后按 run_id 重新挂回。
   */
  const pendingInterviewSources = new Map<
    number,
    { runId: string; source: ChatMessage }
  >()

  function attachInterviewActivity(sessionId: number, runId: string): void {
    const pending = pendingInterviewSources.get(sessionId)
    if (!pending || pending.runId !== runId) return
    pendingInterviewSources.delete(sessionId)
    attachActivity(sessionId, `${runId}:interview`, pending.source)
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

  const EVALUATION_POLL_INTERVAL_MS = 2000
  const EVALUATION_POLL_MAX_ATTEMPTS = 6

  /**
   * 挂断面试后的自动复盘由后台任务生成：结束接口返回时消息可能尚未落库，
   * 或仍是「生成中」占位。轮询刷新该会话，直到复盘消息完成 / 失败或尝试耗尽，
   * 避免用户回到聊天页时看不到复盘卡片。
   */
  async function waitForInterviewEvaluation(
    sessionId: number,
    interviewId: number,
  ): Promise<void> {
    const requestId = `interview:${interviewId}:evaluation`
    for (let attempt = 0; attempt < EVALUATION_POLL_MAX_ATTEMPTS; attempt += 1) {
      if (attempt > 0) {
        await new Promise((resolve) => {
          setTimeout(resolve, EVALUATION_POLL_INTERVAL_MS)
        })
      }
      try {
        await refresh(sessionId)
      } catch {
        return
      }
      const item = stateOf(sessionId).items.find(
        (message) => message.requestId === requestId,
      )
      // status=0 为生成中占位；完成（1）或失败（2）都停止轮询
      if (item && item.status !== 0) return
    }
  }

  function clear(sessionId: number): void {
    delete states.value[sessionId]
    pendingInterviewSources.delete(sessionId)
  }

  /** 退出 / 切换账号时清空消息缓存与发送态，避免串用上一个账号的数据 */
  function reset(): void {
    states.value = {}
    sendingBySession.value = {}
    pendingInterviewSources.clear()
    autoOpenQuizIds.clear()
  }

  function isSending(sessionId: number): boolean {
    return Boolean(sendingBySession.value[sessionId])
  }

  /**
   * 发送一条消息：统一走总控接口 /agent/chat（始终 SSE）。
   *
   * 本地先插入一条「生成中」消息；聊天分支由 meta/delta/done 增量更新，
   * 任务分支在 task 事件到达后先本地渲染，再刷新会话用落库消息对账。
   * `preferredAgent` 只是一次性提示，未选择时由后端总控自行判断。
   * 失败时标记 status=2 并把错误抛给调用方提示。
   */
  async function sendMessage(
    sessionId: number,
    text: string,
    preferredAgent: string | null,
    options: SendMessageOptions = {},
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
      payloadType: null,
      interviewEvaluation: null,
      loadingHint:
        preferredAgent === AgentName.Difficulty
          ? KNOWLEDGE_LOADING_HINT
          : undefined,
      // 路由规划在建立流之前同步完成，后端无法推送；先本地预置即时反馈
      activity: [
        {
          node: 'route',
          agent: 'flow_controller',
          title: '理解请求',
          status: AgentActivityStatus.Running,
          detail: null,
          error: null,
        },
      ],
      errorText: null,
      interviewId: null,
      createdAt,
    })
    state.total += 1
    // 从响应式数组取回代理，直接修改原始对象不会触发视图更新
    const item = state.items[state.items.length - 1]

    sendingBySession.value[sessionId] = true
    let received = ''
    const tasks: AgentTaskResult[] = []
    try {
      await conversationApi.agentChat(
        sessionId,
        { text: content, preferredAgent: preferredAgent ?? undefined },
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
          onAgent: (step) => {
            // 任务能力耗时较长，受理时先给出等待提示；聊天已有默认「正在生成…」
            if (step.phase !== 'start' || step.to === CHAT_AGENT_NAME) return
            item.loadingHint =
              step.to === AgentName.Difficulty
                ? KNOWLEDGE_LOADING_HINT
                : '正在执行任务，请稍等…'
          },
          onStep: (step) => {
            // 收到真实节点进度后，替换掉旧的整段等待文案
            item.loadingHint = undefined
            upsertActivity(item, step)
          },
          onError: (message) => {
            failActivity(item, message)
          },
          onDelta: (delta) => {
            item.loadingHint = undefined
            received += delta
            item.responseText = received
          },
          onTask: (task) => {
            tasks.push(task)
          },
          onDone: (done) => {
            // 来源只挂在消息结构上展示，不拼进 responseText
            item.sources = done.sources
            if (done.messageId > 0) item.id = done.messageId
          },
        },
      )
      item.status = 1

      // 任务分支：页面可接管（面试背景确认），否则本地渲染后刷新对账
      for (const task of tasks) {
        if (task.kind === AgentTaskKind.InterviewPrepare) {
          // 记下时间轴来源，确认面试 refresh 后回挂到 {run_id}:interview 入口消息
          pendingInterviewSources.set(sessionId, {
            runId: task.data.runId,
            source: item,
          })
        }
        const handled = options.onTaskResult?.(task) ?? false
        if (handled) continue

        if (task.kind === AgentTaskKind.KnowledgeCard) {
          // 先按事件结果渲染，再用历史消息对账；刷新失败也保留已渲染的知识卡
          applyKnowledgeCard(item, task.data)
          try {
            await refresh(sessionId)
            attachActivity(sessionId, `${task.data.runId}:card`, item)
          } catch {
            // 重进会话时会重新拉取历史消息
          }
        } else if (task.kind === AgentTaskKind.Quiz) {
          const requestId = `${task.data.runId}:quiz`
          try {
            await refresh(sessionId)
            attachActivity(sessionId, requestId, item)
          } catch {
            // 刷新失败保留临时行：测评入口仍可用，下次刷新 / 重进会话自动对账
            item.requestId = requestId
            item.responsePayload = task.data.quiz
            item.responseText = '已完成出题，请完成后提交答案。'
          }
          // 只给刚生成的测评自动弹窗资格；刷新页面后从历史消息还原的旧试题不再弹
          markQuizAutoOpen(requestId)
        } else if (task.kind === AgentTaskKind.InterviewEvaluation) {
          // 复盘消息已由后端落库：先本地渲染，再用刷新结果对账
          item.payloadType = 'interview_evaluation'
          item.interviewEvaluation = task.data
          item.responseText = `本次面试复盘评分：${task.data.score}/100。`
          try {
            await refresh(sessionId)
            attachActivity(
              sessionId,
              `interview:${task.data.interviewId}:evaluation`,
              item,
            )
          } catch {
            // 刷新失败保留本地复盘卡片，重进会话后可看到落库消息
          }
        } else if (task.kind === AgentTaskKind.Note) {
          item.responseText = `已生成笔记「${task.data.title}」，可在笔记本中查看。`
          try {
            await refresh(sessionId)
            attachActivity(sessionId, `note:${task.data.noteId}`, item)
          } catch {
            // 刷新失败保留本地提示，重进会话后可看到落库消息
          }
        } else {
          // 面试准备未被页面接管：保留用户消息并给出提示，等待二次确认
          item.responseText = '已生成面试背景，请确认后开始面试。'
        }
      }
    } catch (error) {
      item.status = 2
      failActivity(item, error instanceof Error ? error.message : null)
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
      target.payloadType = null
      target.status = 1
    }

    try {
      await refresh(sessionId)
      if (target) attachActivity(sessionId, requestId, target)
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
    waitForInterviewEvaluation,
    attachInterviewActivity,
    consumeQuizAutoOpen,
    clear,
    reset,
    isSending,
    sendMessage,
    submitQuiz,
  }
})
