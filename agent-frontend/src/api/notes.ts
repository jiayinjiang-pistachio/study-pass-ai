import { request } from './request'
import type { PageResult } from '@/types/api'
import type { Note, NoteSummary } from '@/types/note'

interface RawNoteItem {
  id?: number
  session_id?: number
  note_type?: string
  title?: string
  tags?: unknown
  created_at?: number
  updated_at?: number
}

interface RawNote extends RawNoteItem {
  content?: string
}

interface RawSession {
  id?: number
}

function toNumber(value: unknown): number {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return 0
}

function toTags(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.filter((item): item is string => typeof item === 'string')
}

function toSummary(raw: RawNoteItem): NoteSummary {
  return {
    id: toNumber(raw.id),
    sessionId: toNumber(raw.session_id),
    noteType: typeof raw.note_type === 'string' ? raw.note_type : 'manual',
    title: typeof raw.title === 'string' ? raw.title : '',
    tags: toTags(raw.tags),
    createdAt: toNumber(raw.created_at) * 1000,
    updatedAt: toNumber(raw.updated_at) * 1000,
  }
}

function toNote(raw: RawNote): Note {
  return {
    ...toSummary(raw),
    content: typeof raw.content === 'string' ? raw.content : '',
  }
}

export interface NoteListQuery {
  page?: number
  pageSize?: number
  noteType?: string
  keyword?: string
}

export interface CreateNotePayload {
  sessionId: number
  title: string
  content: string
  noteType?: string
}

export interface UpdateNotePayload {
  title?: string
  content?: string
}

export interface UpdateNoteOptions {
  /** 自动保存时关闭错误提示 */
  silent?: boolean
}

/** 分页查询当前用户的笔记（列表不含正文） */
export async function listNotes(
  query: NoteListQuery = {},
): Promise<PageResult<NoteSummary>> {
  const data = await request<PageResult<RawNoteItem>>('/notes', {
    params: {
      page: query.page ?? 1,
      page_size: query.pageSize ?? 100,
      note_type: query.noteType,
      keyword: query.keyword,
    },
  })
  return { ...data, items: data.items.map(toSummary) }
}

/** 查询笔记详情，包含正文 */
export async function getNote(id: number): Promise<Note> {
  const data = await request<RawNote>(`/notes/${id}`)
  return toNote(data)
}

/** 创建笔记：后端要求关联一个属于当前用户的会话 */
export async function createNote(payload: CreateNotePayload): Promise<Note> {
  const data = await request<RawNote>('/notes', {
    method: 'POST',
    body: {
      session_id: payload.sessionId,
      note_type: payload.noteType ?? 'manual',
      title: payload.title,
      content: payload.content,
    },
  })
  return toNote(data)
}

/** 局部更新标题 / 正文 */
export async function updateNote(
  id: number,
  payload: UpdateNotePayload,
  options: UpdateNoteOptions = {},
): Promise<Note> {
  const data = await request<RawNote>(`/notes/${id}`, {
    method: 'PUT',
    body: payload,
    silent: options.silent,
  })
  return toNote(data)
}

export function deleteNote(id: number): Promise<null> {
  return request<null>(`/notes/${id}`, { method: 'DELETE' })
}

/**
 * 笔记创建接口要求 session_id，但笔记页按 note_id 驱动。
 * 这里复用（或创建）一个 session_mode=2 的笔记会话作为归属容器。
 */
export async function ensureNoteSession(): Promise<number> {
  const page = await request<PageResult<RawSession>>('/sessions', {
    params: { page: 1, page_size: 1, session_mode: 2 },
    silent: true,
  })
  const existing = page.items[0]
  if (existing) return toNumber(existing.id)

  const created = await request<RawSession>('/sessions', {
    method: 'POST',
    body: { title: '笔记本', session_mode: 2 },
    silent: true,
  })
  return toNumber(created.id)
}
