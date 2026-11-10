import { ApiError, handleAuthExpired, refreshAccessToken, request } from './request'
import type { PageResult } from '@/types/api'
import type {
  ChatMessage,
  InterviewBackground,
  InterviewEvaluation,
  InterviewPrepareData,
  MessageSegment,
  MessageSource,
  SegmentType,
} from '@/types/chat'
import type { ChatModule, Conversation } from '@/types/conversation'
import { MODULE_ICONS, ModuleKey, SESSION_MODE_BY_MODULE } from '@/types/conversation'
import type { QuizQuestion } from '@/types/quiz'
import { normalizeQuizPayload } from '@/utils/quiz'
import { readSse } from '@/utils/sse'
import { getAccessToken } from '@/utils/token'

const API_PREFIX = import.meta.env.VITE_API_PREFIX || '/api'

interface RawSession {
  id?: number
  title?: string
  session_mode?: number
  created_at?: number
}

interface RawPage<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

interface RawMessage {
  id?: number
  request_id?: string | null
  request_text?: string | null
  response_text?: string | null
  request_segments?: unknown
  response_segments?: unknown
  response_payload?: unknown
  sources?: unknown
  status?: number | null
  interview_id?: number | string | null
  created_at?: number | null
}

const IMAGE_EXT = /\.(png|jpe?g|gif|webp|bmp|svg|avif)(?:[?#].*)?$/i
const AUDIO_EXT = /\.(mp3|wav|ogg|opus|m4a|aac|flac|webm)(?:[?#].*)?$/i

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function toNumber(value: unknown): number {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return 0
}

function toConversation(raw: RawSession): Conversation {
  const module =
    raw.session_mode === 1 ? ModuleKey.Interview : ModuleKey.Study
  return {
    id: toNumber(raw.id),
    title: raw.title ?? '',
    icon: MODULE_ICONS[module],
    module,
    createdAt: toNumber(raw.created_at) * 1000,
  }
}

function toSegmentType(value: unknown, hint: string): SegmentType {
  if (value === 'file' || value === 'image' || value === 'audio') return value
  if (IMAGE_EXT.test(hint)) return 'image'
  if (AUDIO_EXT.test(hint)) return 'audio'
  return 'file'
}

function toSegment(raw: unknown): MessageSegment | null {
  if (!isRecord(raw)) return null
  const name =
    typeof raw.name === 'string'
      ? raw.name
      : typeof raw.file_name === 'string'
        ? raw.file_name
        : ''
  const url = typeof raw.url === 'string' ? raw.url : ''
  return {
    type: toSegmentType(raw.type, name || url),
    resourceId: toNumber(raw.resource_id),
    name,
    url,
  }
}

function toSegments(value: unknown): MessageSegment[] {
  if (!Array.isArray(value)) return []
  return value
    .map(toSegment)
    .filter((segment): segment is MessageSegment => segment !== null)
}

function toSource(raw: unknown): MessageSource | null {
  if (!isRecord(raw)) return null
  const chunkId = typeof raw.chunk_id === 'string' ? raw.chunk_id : ''
  const text = typeof raw.text === 'string' ? raw.text : ''
  if (!chunkId || !text) return null
  return {
    chunkId,
    resourceId: toNumber(raw.resource_id) || null,
    chunkIndex:
      typeof raw.chunk_index === 'number' && Number.isFinite(raw.chunk_index)
        ? raw.chunk_index
        : null,
    fileName: typeof raw.file_name === 'string' ? raw.file_name : '',
    score:
      typeof raw.score === 'number' && Number.isFinite(raw.score)
        ? raw.score
        : null,
    text,
  }
}

function toSources(value: unknown): MessageSource[] {
  if (!Array.isArray(value)) return []
  return value
    .map(toSource)
    .filter((source): source is MessageSource => source !== null)
}

function toPayloadType(
  value: unknown,
): ChatMessage['payloadType'] {
  if (!isRecord(value)) return null
  if (value.type === 'knowledge_card') return 'knowledge_card'
  if (value.type === 'interview_evaluation') return 'interview_evaluation'
  return null
}

function toStringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter(
        (item): item is string => typeof item === 'string' && item.length > 0,
      )
    : []
}

/** 面试复盘载荷：只接受契约字段，缺失评分视为无效载荷 */
function toInterviewEvaluation(value: unknown): InterviewEvaluation | null {
  if (!isRecord(value) || value.type !== 'interview_evaluation') return null
  return {
    interviewId: toNumber(value.interview_id),
    score: toNumber(value.score),
    strengths: toStringList(value.strengths),
    weaknesses: toStringList(value.weaknesses),
    review: toText(value.review),
  }
}

function toMessage(raw: RawMessage): ChatMessage {
  const status = raw.status === 0 || raw.status === 2 ? raw.status : 1
  const createdSeconds = toNumber(raw.created_at)
  const requestId =
    typeof raw.request_id === 'string' && raw.request_id.trim()
      ? raw.request_id
      : null
  // 只有测评题目载荷会渲染答题入口；普通聊天 / 评分后归一为空
  const quiz = normalizeQuizPayload(raw.response_payload)
  return {
    id: toNumber(raw.id),
    requestId,
    requestText: raw.request_text ?? '',
    responseText: raw.response_text ?? '',
    requestSegments: toSegments(raw.request_segments),
    responseSegments: toSegments(raw.response_segments),
    sources: toSources(raw.sources),
    status,
    responsePayload: quiz.length ? quiz : null,
    payloadType: toPayloadType(raw.response_payload),
    interviewEvaluation: toInterviewEvaluation(raw.response_payload),
    interviewId: toNumber(raw.interview_id) || null,
    createdAt: createdSeconds > 0 ? createdSeconds * 1000 : Date.now(),
  }
}

/** 分页获取当前模块的会话，后端按 session_mode 过滤 */
export async function fetchConversations(
  module: ChatModule,
  page: number,
  pageSize: number,
): Promise<PageResult<Conversation>> {
  const data = await request<RawPage<RawSession>>('/sessions', {
    params: {
      page,
      page_size: pageSize,
      session_mode: SESSION_MODE_BY_MODULE[module],
    },
  })
  return { ...data, items: data.items.map(toConversation) }
}

export async function createConversation(
  module: ChatModule,
): Promise<Conversation> {
  const data = await request<RawSession>('/sessions', {
    method: 'POST',
    body: {
      title: module === ModuleKey.Interview ? '新面试会话' : '新学习会话',
      session_mode: SESSION_MODE_BY_MODULE[module],
    },
  })
  return toConversation(data)
}

export async function renameConversation(
  id: number,
  title: string,
): Promise<Conversation> {
  const data = await request<RawSession>(`/sessions/${id}`, {
    method: 'PUT',
    body: { title },
  })
  return toConversation(data)
}

export function deleteConversation(id: number): Promise<null> {
  return request<null>(`/sessions/${id}`, { method: 'DELETE' })
}

/** 分页获取会话消息；附件段与时间在此层统一归一 */
export async function fetchMessages(
  sessionId: number,
  page: number,
  pageSize: number,
): Promise<PageResult<ChatMessage>> {
  const data = await request<RawPage<RawMessage>>(
    `/sessions/${sessionId}/messages`,
    { params: { page, page_size: pageSize } },
  )
  return { ...data, items: data.items.map(toMessage) }
}

/** 流式对话入参：正文与附件段分离，与后端 chat_messages 语义一致 */
export interface StreamChatPayload {
  request_text: string
  select_mode?: number
  request_id?: string
  request_segments?: Array<{
    type: SegmentType
    resource_id: number
    file_name?: string
    url?: string
  }>
}

export interface StreamMeta {
  sessionId: number
  messageId: number
  requestId: string
}

export interface StreamDone {
  messageId: number
  status: number
  /** 本轮回答参考的知识片段；未检索或未命中为空数组 */
  sources: MessageSource[]
}

export interface StreamChatHandlers {
  /** 收到 meta：服务端已完成落库，返回真实消息 ID */
  onMeta?: (meta: StreamMeta) => void
  /** 收到增量文本 */
  onDelta?: (content: string) => void
  /** 收到 done：本轮生成完成，携带完整来源列表 */
  onDone?: (done: StreamDone) => void
}

function buildStreamHeaders(token: string | null): Headers {
  const headers = new Headers()
  headers.set('Content-Type', 'application/json')
  headers.set('Accept', 'text/event-stream')
  if (token) headers.set('Authorization', `Bearer ${token}`)
  return headers
}

async function postStream(url: string, body: unknown): Promise<Response> {
  const init: RequestInit = { method: 'POST', body: JSON.stringify(body) }
  let response = await fetch(url, {
    ...init,
    headers: buildStreamHeaders(getAccessToken()),
  })
  if (response.status !== 401) return response

  // fetch 不经过 axios 拦截器，401 时手动续期并重试一次
  let token: string
  try {
    token = await refreshAccessToken()
  } catch (error) {
    handleAuthExpired('登录状态已过期，请重新登录')
    throw error
  }
  return fetch(url, { ...init, headers: buildStreamHeaders(token) })
}

async function toStreamError(response: Response): Promise<ApiError> {
  let message = `请求失败（${response.status}）`
  try {
    const payload: unknown = await response.json()
    if (isRecord(payload) && typeof payload.message === 'string') {
      message = payload.message
    }
  } catch {
    // 非 JSON 错误体：保留默认文案
  }
  return new ApiError(message, response.status)
}

/** 消费 SSE 响应体：meta → delta* → done，服务端 error 或连接中断抛 ApiError */
async function consumeChatStream(
  response: Response,
  handlers: StreamChatHandlers,
): Promise<void> {
  let errorMessage = ''
  let finished = false

  await readSse(response, ({ event, data }) => {
    let parsed: unknown
    try {
      parsed = JSON.parse(data)
    } catch {
      return
    }
    if (!isRecord(parsed)) return

    if (event === 'meta') {
      handlers.onMeta?.({
        sessionId: toNumber(parsed.session_id),
        messageId: toNumber(parsed.message_id),
        requestId: typeof parsed.request_id === 'string' ? parsed.request_id : '',
      })
    } else if (event === 'delta') {
      if (typeof parsed.content === 'string' && parsed.content) {
        handlers.onDelta?.(parsed.content)
      }
    } else if (event === 'done') {
      finished = true
      handlers.onDone?.({
        messageId: toNumber(parsed.message_id),
        status: toNumber(parsed.status),
        sources: toSources(parsed.sources),
      })
    } else if (event === 'error') {
      errorMessage =
        typeof parsed.message === 'string'
          ? parsed.message
          : 'AI 服务暂时不可用，请稍后重试'
    }
  })

  if (errorMessage) throw new ApiError(errorMessage, 502)
  if (!finished) throw new ApiError('连接中断，请稍后重试', -1)
}

/**
 * 发起流式对话：POST /sessions/{id}/stream-chat。
 *
 * @deprecated 聊天已统一走总控接口 agentChat；保留此函数便于回滚。
 */
export async function streamChat(
  sessionId: number,
  payload: StreamChatPayload,
  handlers: StreamChatHandlers = {},
): Promise<void> {
  const response = await postStream(
    `${API_PREFIX}/sessions/${sessionId}/stream-chat`,
    payload,
  )
  if (!response.ok) throw await toStreamError(response)
  await consumeChatStream(response, handlers)
}

export interface AgentChatInput {
  text: string
  /** 一次性快捷指令提示；未选择或后端不适用时由总控自行判断 */
  preferredAgent?: string
  selectMode?: number
}

export interface AgentWorkflowData {
  runId: string
  status: string
  quiz: QuizQuestion[]
}

/** 知识卡工作流结果：图片必返，音频可空（失败不影响知识卡） */
export interface KnowledgeCardData {
  runId: string
  title: string
  imageResourceId: number
  imageUrl: string
  audioResourceId: number | null
  audioUrl: string | null
}

/** 笔记归档结果：同时写入会话消息，前端刷新后可见入口文案 */
export interface NoteTaskData {
  runId: string
  noteId: number
  title: string
}

/** 面试复盘结果：后端已落库为会话消息，前端先本地渲染再刷新对账 */
export interface InterviewEvaluationData extends InterviewEvaluation {
  runId: string
}

/** task 事件的任务类型，与后端 orchestrator 的 kind 保持一致 */
export const AgentTaskKind = {
  Quiz: 'quiz',
  KnowledgeCard: 'knowledge_card',
  InterviewPrepare: 'interview_prepare',
  InterviewEvaluation: 'interview_evaluation',
  Note: 'note',
} as const
export type AgentTaskKind = (typeof AgentTaskKind)[keyof typeof AgentTaskKind]

/** 总控任务事件归一后的结果；聊天分支不会产生 task 事件 */
export type AgentTaskResult =
  | { kind: typeof AgentTaskKind.Quiz; data: AgentWorkflowData }
  | { kind: typeof AgentTaskKind.KnowledgeCard; data: KnowledgeCardData }
  | { kind: typeof AgentTaskKind.InterviewPrepare; data: InterviewPrepareData }
  | { kind: typeof AgentTaskKind.InterviewEvaluation; data: InterviewEvaluationData }
  | { kind: typeof AgentTaskKind.Note; data: NoteTaskData }

/** 调度可观测信息：前端可据此展示「正在调用 xx 智能体」 */
export interface AgentStepInfo {
  traceId: string
  from: string
  to: string
  phase: string
  reason: string
}

export interface AgentStreamHandlers extends StreamChatHandlers {
  onAgent?: (step: AgentStepInfo) => void
  onTask?: (task: AgentTaskResult) => void
}

function toText(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

/** 面试背景：后端字段为 snake_case，统一归一为前端 camelCase */
function toInterviewBackground(raw: unknown): InterviewBackground {
  const source = isRecord(raw) ? raw : {}
  return {
    targetJob: toText(source.target_job),
    targetLevel: toText(source.target_level),
    yearsExperience: toText(source.years_experience),
    targetSkills: toText(source.target_skills),
    projectExperience: toText(source.project_experience),
    weakTopics: toText(source.weak_topics),
    openingQuestion: toText(source.opening_question),
  }
}

/** 第一阶段面试准备：只返回待确认背景，由页面弹窗承接 */
function toInterviewPrepare(
  runId: string,
  data: Record<string, unknown>,
): AgentTaskResult {
  if (data.status !== 'pending_confirmation') {
    throw new ApiError('面试准备状态异常，请重新发起', 502)
  }
  const resume = isRecord(data.resume) ? data.resume : {}
  return {
    kind: AgentTaskKind.InterviewPrepare,
    data: {
      runId,
      sessionId: toNumber(data.session_id),
      resumeFileName: toText(resume.file_name),
      background: toInterviewBackground(data.background),
    },
  }
}

/** 知识卡结果：图片必返，音频可空；缺少图片资源视为响应异常 */
function toKnowledgeCard(
  runId: string,
  data: Record<string, unknown>,
): AgentTaskResult {
  const imageResourceId = toNumber(data.resource_id)
  if (!imageResourceId) throw new ApiError('知识卡响应缺少图片资源', 502)

  const audioResourceId = toNumber(data.audio_resource_id) || null
  return {
    kind: AgentTaskKind.KnowledgeCard,
    data: {
      runId,
      title: toText(data.title) || '知识卡',
      imageResourceId,
      imageUrl: toText(data.image_url),
      audioResourceId,
      audioUrl: audioResourceId ? toText(data.audio_url) : null,
    },
  }
}

function toQuizTask(data: Record<string, unknown>): AgentTaskResult {
  return {
    kind: AgentTaskKind.Quiz,
    data: {
      runId: toText(data.run_id),
      status: toText(data.status),
      quiz: normalizeQuizPayload(data.quiz),
    },
  }
}

function toNoteTask(runId: string, data: Record<string, unknown>): AgentTaskResult {
  const noteId = toNumber(data.note_id)
  if (!noteId) throw new ApiError('笔记任务缺少 note_id', 502)
  return {
    kind: AgentTaskKind.Note,
    data: {
      runId: runId || toText(data.run_id),
      noteId,
      title: toText(data.title) || '笔记',
    },
  }
}

function toInterviewEvaluationTask(
  runId: string,
  data: Record<string, unknown>,
): AgentTaskResult {
  const interviewId = toNumber(data.interview_id)
  if (!interviewId) throw new ApiError('面试复盘响应缺少 interview_id', 502)
  return {
    kind: AgentTaskKind.InterviewEvaluation,
    data: {
      runId: runId || toText(data.run_id),
      interviewId,
      score: toNumber(data.score),
      strengths: toStringList(data.strengths),
      weaknesses: toStringList(data.weaknesses),
      review: toText(data.review),
    },
  }
}

/** task 事件载荷按 kind 归一；未知类型说明前后端契约不一致 */
function toTaskResult(
  kind: string,
  runId: string,
  payload: unknown,
): AgentTaskResult {
  const data = isRecord(payload) ? payload : {}
  switch (kind) {
    case AgentTaskKind.Quiz:
      return toQuizTask(data)
    case AgentTaskKind.KnowledgeCard:
      return toKnowledgeCard(runId || toText(data.run_id), data)
    case AgentTaskKind.InterviewPrepare:
      return toInterviewPrepare(runId || toText(data.run_id), data)
    case AgentTaskKind.InterviewEvaluation:
      return toInterviewEvaluationTask(runId || toText(data.run_id), data)
    case AgentTaskKind.Note:
      return toNoteTask(runId, data)
    default:
      throw new ApiError('未知的任务类型，请稍后重试', 502)
  }
}

/** 消费总控 SSE：meta → agent → delta / task → done，error 抛 ApiError */
async function consumeAgentStream(
  response: Response,
  handlers: AgentStreamHandlers,
): Promise<void> {
  let errorMessage = ''
  let finished = false

  await readSse(response, ({ event, data }) => {
    let parsed: unknown
    try {
      parsed = JSON.parse(data)
    } catch {
      return
    }
    if (!isRecord(parsed)) return

    if (event === 'meta') {
      handlers.onMeta?.({
        sessionId: toNumber(parsed.session_id),
        messageId: toNumber(parsed.message_id),
        requestId: typeof parsed.request_id === 'string' ? parsed.request_id : '',
      })
    } else if (event === 'agent') {
      handlers.onAgent?.({
        traceId: toText(parsed.trace_id),
        from: toText(parsed.from),
        to: toText(parsed.to),
        phase: toText(parsed.phase),
        reason: toText(parsed.reason),
      })
    } else if (event === 'delta') {
      if (typeof parsed.content === 'string' && parsed.content) {
        handlers.onDelta?.(parsed.content)
      }
    } else if (event === 'task') {
      const kind = toText(parsed.kind)
      const runId = toText(parsed.run_id)
      const task = toTaskResult(kind, runId, parsed.payload)
      handlers.onTask?.(task)
    } else if (event === 'done') {
      finished = true
      handlers.onDone?.({
        messageId: toNumber(parsed.message_id),
        status: toNumber(parsed.status),
        sources: toSources(parsed.sources),
      })
    } else if (event === 'error') {
      errorMessage =
        typeof parsed.message === 'string'
          ? parsed.message
          : 'AI 服务暂时不可用，请稍后重试'
    }
  })

  if (errorMessage) throw new ApiError(errorMessage, 502)
  if (!finished) throw new ApiError('连接中断，请稍后重试', -1)
}

/**
 * 总控聊天：POST /agent/chat，始终返回 SSE。
 *
 * 普通聊天逐条下发 delta；任务分支在完成时下发 task 事件，
 * 调用方按 kind 刷新会话或接管页面（如面试背景确认弹窗）。
 */
export async function agentChat(
  sessionId: number,
  input: AgentChatInput,
  handlers: AgentStreamHandlers = {},
): Promise<void> {
  const response = await postStream(`${API_PREFIX}/agent/chat`, {
    session_id: sessionId,
    request_text: input.text,
    preferred_agent: input.preferredAgent,
    select_mode: input.selectMode ?? 0,
  })
  if (!response.ok) throw await toStreamError(response)
  await consumeAgentStream(response, handlers)
}
