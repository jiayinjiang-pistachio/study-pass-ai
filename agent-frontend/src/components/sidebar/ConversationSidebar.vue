<script setup lang="ts">
import { Plus } from '@element-plus/icons-vue'
import ConversationList from './ConversationList.vue'
import { useConversationStore } from '@/stores/conversation'

const conversationStore = useConversationStore()

async function handleCreate(): Promise<void> {
  await conversationStore.create()
}
</script>

<template>
  <aside class="sidebar">
    <button type="button" class="sidebar__create" @click="handleCreate">
      <el-icon><Plus /></el-icon>
      <span>新建会话</span>
    </button>

    <p class="sidebar__label">历史会话</p>

    <ConversationList />
  </aside>
</template>

<style lang="scss" scoped>
.sidebar {
  flex: none;
  display: flex;
  flex-direction: column;
  width: var(--sidebar-width);
  padding: 20px 16px;
  background: var(--color-surface);
  border-right: 1px solid var(--color-divider);

  &__create {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    width: 100%;
    height: 46px;
    border: none;
    border-radius: var(--radius-control);
    background: linear-gradient(90deg, var(--color-brand-light), var(--color-brand));
    color: #fff;
    font-size: 15px;
    font-weight: 600;
    cursor: pointer;
    box-shadow: 0 4px 10px rgba(245, 197, 24, 0.3);
    transition: filter 0.2s;

    &:hover {
      filter: brightness(1.03);
    }

    &:active {
      filter: brightness(0.97);
    }
  }

  &__label {
    margin: 22px 0 10px;
    padding-left: 10px;
    font-size: 13px;
    color: var(--color-text-muted);
  }

  @media (max-width: 768px) {
    display: none;
  }
}
</style>
