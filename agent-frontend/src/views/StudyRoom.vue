<script setup lang="ts">
import ChatMessageList from '@/components/chat/ChatMessageList.vue'
import ChatInputBar from '@/components/chat/ChatInputBar.vue'
</script>

<template>
  <div class="study-room">
    <ChatMessageList />
    <ChatInputBar />
  </div>
</template>

<style lang="scss" scoped>
.study-room {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}
</style>
