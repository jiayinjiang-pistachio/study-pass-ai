import { request } from './request'
import type { ChatMessage } from '@/types/chat'
import type { Conversation } from '@/types/conversation'

export function fetchConversations(): Promise<Conversation[]> {
  return request<Conversation[]>('/conversations')
}

export function fetchMessages(conversationId: string): Promise<ChatMessage[]> {
  return request<ChatMessage[]>(`/conversations/${conversationId}/messages`)
}

export function createConversation(): Promise<Conversation> {
  return request<Conversation>('/conversations', { method: 'POST' })
}

export function renameConversation(id: string, title: string): Promise<Conversation> {
  return request<Conversation>(`/conversations/${id}`, { method: 'PUT', body: { title } })
}

export function deleteConversation(id: string): Promise<null> {
  return request<null>(`/conversations/${id}`, { method: 'DELETE' })
}
