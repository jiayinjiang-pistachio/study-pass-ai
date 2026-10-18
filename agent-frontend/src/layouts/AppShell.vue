<script setup lang="ts">
import { onMounted } from 'vue'
import TopNavBar from '@/components/layout/TopNavBar.vue'
import ConversationSidebar from '@/components/sidebar/ConversationSidebar.vue'
import { useConversationStore } from '@/stores/conversation'

const conversationStore = useConversationStore()

onMounted(() => {
  void conversationStore.load()
})
</script>

<template>
  <div class="app-shell">
    <TopNavBar />

    <div class="app-shell__body">
      <ConversationSidebar />

      <main class="app-shell__content">
        <RouterView />
      </main>
    </div>
  </div>
</template>

<style lang="scss" scoped>
.app-shell {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;

  &__body {
    flex: 1;
    display: flex;
    min-height: 0;
  }

  &__content {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    background: var(--color-bg-page);
  }
}
</style>
