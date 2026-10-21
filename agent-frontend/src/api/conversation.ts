import { request } from './request'
import type { PageResult } from '@/types/api'
import type { ChatMessage, MessageSegment, SegmentType } from '@/types/chat'
import type { ChatModule, Conversation } from '@/types/conversation'
import { MODULE_ICONS, ModuleKey, SESSION_MODE_BY_MODULE } from '@/types/conversation'

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

function toMessage(raw: RawMessage): ChatMessage {
  const status = raw.status === 0 || raw.status === 2 ? raw.status : 1
  const createdSeconds = toNumber(raw.created_at)
  return {
    id: toNumber(raw.id),
    requestText: raw.request_text ?? '',
    responseText: raw.response_text ?? '',
    requestSegments: toSegments(raw.request_segments),
    responseSegments: toSegments(raw.response_segments),
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
