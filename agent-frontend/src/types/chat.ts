export type Role = 'ai' | 'user'

export const MessageStatus = {
  Pending: 'pending',
  Streaming: 'streaming',
  Done: 'done',
  Error: 'error',
} as const
export type MessageStatus = (typeof MessageStatus)[keyof typeof MessageStatus]

export interface ChatMessage {
  id: string
  role: Role
  content: string
  createdAt: number
  status?: MessageStatus
}
