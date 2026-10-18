import { ref } from 'vue'
import { defineStore } from 'pinia'
import type { ChatMessage } from '@/types/chat'
import * as conversationApi from '@/api/conversation'
import * as interviewApi from '@/api/interview'

export const useChatStore = defineStore('chat', () => {
  /** conversationId -> 消息列表 */
  const messagesMap = ref<Record<string, ChatMessage[]>>({})
  const loading = ref(false)

  /** AI 是否正在回复（用于展示「思考中」占位） */
  const replying = ref(false)

  async function loadMessages(conversationId: string): Promise<void> {
    loading.value = true
    try {
      messagesMap.value[conversationId] = await conversationApi.fetchMessages(conversationId)
    } finally {
      loading.value = false
    }
  }

  async function send(conversationId: string, content: string): Promise<void> {
    if (!messagesMap.value[conversationId]) {
      messagesMap.value[conversationId] = []
    }

    // 乐观上屏用户消息，随后由接口返回 AI 回复
    messagesMap.value[conversationId].push({
      id: `local-${Date.now()}`,
      role: 'user',
      content,
      createdAt: Date.now(),
      status: 'done',
    })

    replying.value = true
    try {
      const reply = await interviewApi.sendMessage(conversationId, content)
      messagesMap.value[conversationId].push(reply)
    } finally {
      replying.value = false
    }
  }

  return { messagesMap, loading, replying, loadMessages, send }
})
