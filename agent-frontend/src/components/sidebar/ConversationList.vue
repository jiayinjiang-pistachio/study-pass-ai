<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { ElMessage } from 'element-plus'
import SidebarItem from './SidebarItem.vue'
import { useCurrentModule } from '@/composables/useCurrentModule'
import { useConversationStore } from '@/stores/conversation'

const conversationStore = useConversationStore()
const { conversations, activeByModule, loading } = storeToRefs(conversationStore)
const module = useCurrentModule()

const list = computed(() => conversationStore.listOf(module.value))
const activeId = computed(() => activeByModule.value[module.value])

function handleSelect(id: string): void {
  conversationStore.select(module.value, id)
}

function handleExport(id: string): void {
  const target = conversations.value.find((item) => item.id === id)
  ElMessage.info(`导出「${target?.title ?? ''}」功能开发中`)
}
</script>

<template>
  <ul v-loading="loading" class="sidebar-list scroll-area">
    <SidebarItem
      v-for="item in list"
      :key="item.id"
      :id="item.id"
      :title="item.title"
      :icon="item.icon"
      :active="item.id === activeId"
      entity-label="会话"
      @select="handleSelect"
      @rename="conversationStore.rename"
      @remove="conversationStore.remove"
      @export="handleExport"
    />
  </ul>
</template>
