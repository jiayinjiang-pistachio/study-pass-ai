import { request } from './request'
import type { ChatMessage } from '@/types/chat'

/** 提交用户回答，返回 AI 面试官的回复 */
export function sendMessage(conversationId: string, content: string): Promise<ChatMessage> {
  return request<ChatMessage>(`/conversations/${conversationId}/messages`, {
    method: 'POST',
    body: { content },
  })
}
