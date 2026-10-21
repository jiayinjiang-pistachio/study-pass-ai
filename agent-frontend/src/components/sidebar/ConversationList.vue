<script setup lang="ts">
import { computed } from 'vue'
import { ElMessage } from 'element-plus'
import SidebarItem from './SidebarItem.vue'
import { useCurrentChatModule } from '@/composables/useCurrentModule'
import { useChatStore } from '@/stores/chat'
import { useConversationStore } from '@/stores/conversation'

const conversationStore = useConversationStore()
const chatStore = useChatStore()
const module = useCurrentChatModule()

const state = computed(() =>
  module.value ? conversationStore.stateOf(module.value) : null,
)
const list = computed(() =>
  module.value ? conversationStore.listOf(module.value) : [],
)
const activeId = computed(() =>
  module.value ? conversationStore.activeByModule[module.value] : null,
)
const hasMore = computed(() =>
  module.value ? conversationStore.hasMore(module.value) : false,
)

function handleSelect(id: string | number): void {
  if (!module.value) return
  conversationStore.select(module.value, Number(id))
}

function handleRename(id: string | number, title: string): void {
  if (!module.value) return
  void conversationStore.rename(Number(id), title)
}

async function handleRemove(id: string | number): Promise<void> {
  if (!module.value) return
  const sessionId = Number(id)
  await conversationStore.remove(module.value, sessionId)
  chatStore.clear(sessionId)
}

function handleExport(id: string | number): void {
  const target = list.value.find((item) => item.id === Number(id))
  ElMessage.info(`导出「${target?.title ?? ''}」功能开发中`)
}

function handleLoadMore(): void {
  if (!module.value) return
  void conversationStore.loadMore(module.value)
}
</script>

<template>
  <div class="conversation-list">
    <ul v-loading="state?.loading ?? false" class="sidebar-list scroll-area">
      <SidebarItem
        v-for="item in list"
        :key="item.id"
        :id="item.id"
        :title="item.title"
        :icon="item.icon"
        :active="item.id === activeId"
        entity-label="会话"
        @select="handleSelect"
        @rename="handleRename"
        @remove="handleRemove"
        @export="handleExport"
      />
    </ul>

    <button
      v-if="hasMore"
      type="button"
      class="conversation-list__more"
      :disabled="state?.loading ?? false"
      @click="handleLoadMore"
    >
      {{ state?.loading ? '加载中…' : '加载更多' }}
    </button>
  </div>
</template>

<style lang="scss" scoped>
.conversation-list {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;

  &__more {
    flex: none;
    margin-top: 8px;
    padding: 8px 0;
    border: none;
    background: transparent;
    font-size: 13px;
    color: var(--color-text-muted);
    cursor: pointer;

    &:hover:not(:disabled) {
      color: var(--color-text);
    }

    &:disabled {
      cursor: default;
      opacity: 0.6;
    }
  }
}
</style>
