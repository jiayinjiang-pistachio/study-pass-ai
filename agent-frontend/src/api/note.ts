import { request } from './request'
import type { Note } from '@/types/note'

export function fetchNotes(): Promise<Note[]> {
  return request<Note[]>('/notes')
}

export function createNote(): Promise<Note> {
  return request<Note>('/notes', { method: 'POST' })
}

export function renameNote(id: string, title: string): Promise<Note> {
  return request<Note>(`/notes/${id}`, { method: 'PUT', body: { title } })
}

export function saveNoteContent(id: string, content: string): Promise<Note> {
  return request<Note>(`/notes/${id}/content`, { method: 'PUT', body: { content } })
}

export function deleteNote(id: string): Promise<null> {
  return request<null>(`/notes/${id}`, { method: 'DELETE' })
}
