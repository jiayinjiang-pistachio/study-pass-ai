import { ref } from 'vue'
import { defineStore } from 'pinia'
import type { Conversation } from '@/types/conversation'
import * as conversationApi from '@/api/conversation'

export const useConversationStore = defineStore('conversation', () => {
  const conversations = ref<Conversation[]>([])
  const activeConversationId = ref('')
  const loading = ref(false)

  async function load(): Promise<void> {
    loading.value = true
    try {
      const list = await conversationApi.fetchConversations()
      conversations.value = list
      if (!list.some((c) => c.id === activeConversationId.value)) {
        activeConversationId.value = list[0]?.id ?? ''
      }
    } finally {
      loading.value = false
    }
  }

  function select(id: string): void {
    activeConversationId.value = id
  }

  async function create(): Promise<void> {
    const conversation = await conversationApi.createConversation()
    conversations.value.unshift(conversation)
    activeConversationId.value = conversation.id
  }

  async function rename(id: string, title: string): Promise<void> {
    const trimmed = title.trim()
    if (!trimmed) return
    const updated = await conversationApi.renameConversation(id, trimmed)
    const target = conversations.value.find((c) => c.id === id)
    if (target) target.title = updated.title
  }

  async function remove(id: string): Promise<void> {
    await conversationApi.deleteConversation(id)
    const index = conversations.value.findIndex((c) => c.id === id)
    if (index === -1) return
    conversations.value.splice(index, 1)
    if (activeConversationId.value === id) {
      const next = conversations.value[index] ?? conversations.value[index - 1]
      activeConversationId.value = next?.id ?? ''
    }
  }

  function touch(id: string): void {
    const target = conversations.value.find((c) => c.id === id)
    if (target) target.updatedAt = Date.now()
  }

  return {
    conversations,
    activeConversationId,
    loading,
    load,
    select,
    create,
    rename,
    remove,
    touch,
  }
})
