<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { ArrowDown, Service } from '@element-plus/icons-vue'
import ChatMessageItem from './ChatMessageItem.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import LoadingDots from '@/components/common/LoadingDots.vue'
import { useAutoScroll } from '@/composables/useAutoScroll'
import { useCurrentModule } from '@/composables/useCurrentModule'
import { useChatStore } from '@/stores/chat'
import { useConversationStore } from '@/stores/conversation'

const chatStore = useChatStore()
const conversationStore = useConversationStore()
const { messagesMap, loading, replying } = storeToRefs(chatStore)
const module = useCurrentModule()

const scroller = ref<HTMLElement | null>(null)

const activeConversationId = computed(() => conversationStore.activeByModule[module.value])
const messages = computed(() => messagesMap.value[activeConversationId.value] ?? [])

const { showScrollToBottom, scrollToBottom } = useAutoScroll(scroller, () => messages.value)

watch(
  activeConversationId,
  (id) => {
    if (id) void chatStore.loadMessages(id)
  },
  { immediate: true },
)
</script>

<template>
  <div ref="scroller" v-loading="loading" class="chat-list scroll-area">
    <div class="chat-list__inner">
      <template v-if="messages.length">
        <ChatMessageItem v-for="item in messages" :key="item.id" :message="item" />

        <div v-if="replying" class="chat-list__typing">
          <span class="chat-list__typing-avatar">
            <el-icon><Service /></el-icon>
          </span>
          <div class="chat-list__typing-bubble">
            <LoadingDots />
          </div>
        </div>
      </template>

      <EmptyState v-else-if="!loading" description="开始你的第一句话吧" />
    </div>

    <Transition name="fade">
      <button
        v-if="showScrollToBottom"
        type="button"
        class="chat-list__to-bottom"
        @click="scrollToBottom()"
      >
        <el-icon><ArrowDown /></el-icon>
      </button>
    </Transition>
  </div>
</template>

<style lang="scss" scoped>
.chat-list {
  position: relative;
  flex: 1;
  min-height: 0;

  &__inner {
    display: flex;
    flex-direction: column;
    gap: 22px;
    max-width: var(--content-max-width);
    min-height: 100%;
    margin: 0 auto;
    padding: 28px 24px 12px;
  }

  &__typing {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  &__typing-avatar {
    flex: none;
    display: flex;
    align-items: center;
    justify-content: center;
    width: var(--avatar-size);
    height: var(--avatar-size);
    border-radius: 50%;
    background: #3b82f6;
    color: #fff;
    font-size: 20px;
  }

  &__typing-bubble {
    display: flex;
    align-items: center;
    padding: 12px 18px;
    border-radius: var(--radius-bubble);
    background: var(--color-surface);
    border: 1px solid var(--color-border);
  }

  &__to-bottom {
    position: absolute;
    left: 50%;
    bottom: 16px;
    transform: translateX(-50%);
    display: flex;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 36px;
    border: 1px solid var(--color-border);
    border-radius: 50%;
    background: var(--color-surface);
    color: var(--color-text-secondary);
    cursor: pointer;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);

    &:hover {
      color: var(--color-text);
    }
  }
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
