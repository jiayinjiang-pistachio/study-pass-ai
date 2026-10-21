<script setup lang="ts">
import { computed } from 'vue'
import { Plus } from '@element-plus/icons-vue'
import ConversationList from './ConversationList.vue'
import NoteList from './NoteList.vue'
import { useCurrentChatModule, useCurrentModule } from '@/composables/useCurrentModule'
import { useConversationStore } from '@/stores/conversation'
import { useNoteStore } from '@/stores/note'
import { ModuleKey } from '@/types/conversation'

const conversationStore = useConversationStore()
const noteStore = useNoteStore()
const module = useCurrentModule()
const chatModule = useCurrentChatModule()

const isNote = computed(() => module.value === ModuleKey.Note)
const createLabel = computed(() => (isNote.value ? '新建笔记' : '新建会话'))
const listLabel = computed(() => (isNote.value ? '历史笔记' : '历史会话'))

async function handleCreate(): Promise<void> {
  if (isNote.value) {
    await noteStore.create()
  } else if (chatModule.value) {
    await conversationStore.create(chatModule.value)
  }
}
</script>

<template>
  <aside class="sidebar">
    <button type="button" class="sidebar__create" @click="handleCreate">
      <el-icon><Plus /></el-icon>
      <span>{{ createLabel }}</span>
    </button>

    <p class="sidebar__label">{{ listLabel }}</p>

    <NoteList v-if="isNote" />
    <ConversationList v-else />
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
