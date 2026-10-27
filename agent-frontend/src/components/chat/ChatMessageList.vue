<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { ArrowDown } from '@element-plus/icons-vue'
import ChatMessageItem from './ChatMessageItem.vue'
import ProfileWelcomeCard from './ProfileWelcomeCard.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { useAutoScroll } from '@/composables/useAutoScroll'
import { useCurrentChatModule } from '@/composables/useCurrentModule'
import { useChatStore } from '@/stores/chat'
import { useConversationStore } from '@/stores/conversation'
import { useProfileStore } from '@/stores/profile'
import type { ChatMessage } from '@/types/chat'

/** 常量空数组，避免 computed 每次返回新引用触发无意义的 watch */
const EMPTY_MESSAGES: ChatMessage[] = []

const chatStore = useChatStore()
const conversationStore = useConversationStore()
const profileStore = useProfileStore()
const module = useCurrentChatModule()

const scroller = ref<HTMLElement | null>(null)
/** 按会话记录「稍后再说」，本次会话内不再弹出画像卡片 */
const skippedSessions = ref<Record<number, boolean>>({})

const activeSessionId = computed(() =>
  module.value ? conversationStore.activeByModule[module.value] : null,
)
const state = computed(() =>
  activeSessionId.value ? chatStore.stateOf(activeSessionId.value) : null,
)
const messages = computed(() => state.value?.items ?? EMPTY_MESSAGES)
const loading = computed(() => state.value?.loading ?? false)
const loadingOlder = computed(() => state.value?.loadingOlder ?? false)
const hasActiveSession = computed(() => activeSessionId.value !== null)
/** 空会话且画像未填时展示欢迎卡片；跳过或画像已齐全则回到默认空状态 */
const showProfileCard = computed(() => {
  const id = activeSessionId.value
  return (
    id !== null &&
    !loading.value &&
    messages.value.length === 0 &&
    profileStore.needsOnboarding &&
    !skippedSessions.value[id]
  )
})

const { showScrollToBottom, scrollToBottom } = useAutoScroll(
  scroller,
  () => messages.value,
)

watch(
  activeSessionId,
  async (id) => {
    if (id === null) return
    await chatStore.loadLatest(id)
    // 进入空会话时重读画像，避免对话自动回填后仍展示欢迎卡片
    if (chatStore.stateOf(id).items.length === 0) void profileStore.refresh()
    await nextTick()
    scrollToBottom('auto')
  },
  { immediate: true },
)

function handleSkip(): void {
  const id = activeSessionId.value
  if (id !== null) skippedSessions.value[id] = true
}

/** 距离顶部 10px 内触发上拉分页，并保持当前视口位置不跳动 */
async function handleScroll(): Promise<void> {
  const el = scroller.value
  const id = activeSessionId.value
  if (!el || id === null || el.scrollTop > 10) return

  const current = chatStore.stateOf(id)
  if (current.loadingOlder || current.page <= 1) return

  const heightBefore = el.scrollHeight
  const topBefore = el.scrollTop
  const added = await chatStore.loadOlder(id)
  if (!added) return

  await nextTick()
  el.scrollTop = topBefore + (el.scrollHeight - heightBefore)
}
</script>

<template>
  <div
    ref="scroller"
    v-loading="loading"
    class="chat-list scroll-area"
    @scroll.passive="handleScroll"
  >
    <div class="chat-list__inner">
      <p v-if="loadingOlder" class="chat-list__older">加载更早消息…</p>

      <template v-if="messages.length">
        <ChatMessageItem v-for="item in messages" :key="item.id" :message="item" />
      </template>

      <ProfileWelcomeCard
        v-else-if="showProfileCard"
        :key="activeSessionId ?? undefined"
        @skip="handleSkip"
      />
      <EmptyState
        v-else-if="!loading && hasActiveSession"
        description="暂无聊天记录"
      />
      <EmptyState
        v-else-if="!loading"
        description="暂无会话，点击左侧「新建会话」开始"
      />
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

  &__older {
    margin: 0;
    padding: 4px 0;
    text-align: center;
    font-size: 12px;
    color: var(--color-text-muted);
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
