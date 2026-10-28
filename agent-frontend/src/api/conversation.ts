import { ApiError, handleAuthExpired, refreshAccessToken, request } from './request'
import type { PageResult } from '@/types/api'
import type {
  ChatMessage,
  MessageSegment,
  MessageSource,
  SegmentType,
} from '@/types/chat'
import type { ChatModule, Conversation } from '@/types/conversation'
import { MODULE_ICONS, ModuleKey, SESSION_MODE_BY_MODULE } from '@/types/conversation'
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
  request_text?: string | null
  response_text?: string | null
  request_segments?: unknown
  response_segments?: unknown
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

function toMessage(raw: RawMessage): ChatMessage {
  const status = raw.status === 0 || raw.status === 2 ? raw.status : 1
  const createdSeconds = toNumber(raw.created_at)
  return {
    id: toNumber(raw.id),
    requestText: raw.request_text ?? '',
    responseText: raw.response_text ?? '',
    requestSegments: toSegments(raw.request_segments),
    responseSegments: toSegments(raw.response_segments),
    sources: toSources(raw.sources),
    status,
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

/**
 * 发起流式对话：POST /sessions/{id}/stream-chat。
 *
 * EventSource 不支持 POST + Authorization，因此用 fetch 读取 SSE 响应体。
 * 正常流程为 meta → delta* → done；服务端 error 事件或连接中断会抛 ApiError。
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
