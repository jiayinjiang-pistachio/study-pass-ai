import { ref } from 'vue'
import { defineStore } from 'pinia'
import type { Conversation, ModuleKey } from '@/types/conversation'
import { ModuleKey as Module } from '@/types/conversation'
import * as conversationApi from '@/api/conversation'

/** 会话仅存在于学习室与面试间；笔记本使用独立的笔记数据源 */
const CHAT_MODULES: ModuleKey[] = [Module.Study, Module.Interview]

export const useConversationStore = defineStore('conversation', () => {
  const conversations = ref<Conversation[]>([])
  /** 每个模块各自记录当前选中的会话 id（模块由路由决定，见 ConversationSidebar） */
  const activeByModule = ref<Record<ModuleKey, string>>({
    [Module.Study]: '',
    [Module.Interview]: '',
    [Module.Note]: '',
  })
  const loading = ref(false)

  function listOf(module: ModuleKey): Conversation[] {
    return conversations.value.filter((item) => item.module === module)
  }

  async function load(): Promise<void> {
    loading.value = true
    try {
      conversations.value = await conversationApi.fetchConversations()
      CHAT_MODULES.forEach((module) => {
        const list = listOf(module)
        if (!list.some((item) => item.id === activeByModule.value[module])) {
          activeByModule.value[module] = list[0]?.id ?? ''
        }
      })
    } finally {
      loading.value = false
    }
  }

  function select(module: ModuleKey, id: string): void {
    activeByModule.value[module] = id
  }

  async function create(module: ModuleKey): Promise<void> {
    const conversation = await conversationApi.createConversation(module)
    conversations.value.unshift(conversation)
    activeByModule.value[module] = conversation.id
  }

  async function rename(id: string, title: string): Promise<void> {
    const trimmed = title.trim()
    if (!trimmed) return
    const updated = await conversationApi.renameConversation(id, trimmed)
    const target = conversations.value.find((item) => item.id === id)
    if (target) target.title = updated.title
  }

  async function remove(id: string): Promise<void> {
    await conversationApi.deleteConversation(id)
    const index = conversations.value.findIndex((item) => item.id === id)
    if (index === -1) return
    const [removed] = conversations.value.splice(index, 1)
    const module = removed.module
    if (activeByModule.value[module] === id) {
      activeByModule.value[module] = listOf(module)[0]?.id ?? ''
    }
  }

  function touch(id: string): void {
    const target = conversations.value.find((item) => item.id === id)
    if (target) target.updatedAt = Date.now()
  }

  return {
    conversations,
    activeByModule,
    loading,
    listOf,
    load,
    select,
    create,
    rename,
    remove,
    touch,
  }
})
