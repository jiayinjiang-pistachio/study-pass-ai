<script setup lang="ts">
import { storeToRefs } from 'pinia'
import ConversationItem from './ConversationItem.vue'
import { useConversationStore } from '@/stores/conversation'

const conversationStore = useConversationStore()
const { conversations, activeConversationId, loading } = storeToRefs(conversationStore)
</script>

<template>
  <ul v-loading="loading" class="conv-list scroll-area">
    <ConversationItem
      v-for="item in conversations"
      :key="item.id"
      :conversation="item"
      :active="item.id === activeConversationId"
    />
  </ul>
</template>

<style lang="scss" scoped>
.conv-list {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin: 0 -6px;
  padding: 0 6px;
}
</style>
