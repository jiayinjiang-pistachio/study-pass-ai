<script setup lang="ts">
import { nextTick, ref } from 'vue'
import { Delete, Download, Edit } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { Conversation } from '@/types/conversation'
import { useConversationStore } from '@/stores/conversation'

const props = defineProps<{
  conversation: Conversation
  active: boolean
}>()

const conversationStore = useConversationStore()

const editing = ref(false)
const draft = ref('')
const inputRef = ref<HTMLInputElement | null>(null)

function handleSelect(): void {
  if (editing.value) return
  conversationStore.select(props.conversation.id)
}

async function startEdit(): Promise<void> {
  editing.value = true
  draft.value = props.conversation.title
  await nextTick()
  inputRef.value?.focus()
  inputRef.value?.select()
}

function commitEdit(): void {
  if (!editing.value) return
  editing.value = false
  void conversationStore.rename(props.conversation.id, draft.value)
}

function cancelEdit(): void {
  editing.value = false
}

function handleDownload(): void {
  ElMessage.info(`导出「${props.conversation.title}」功能开发中`)
}

async function handleDelete(): Promise<void> {
  try {
    await ElMessageBox.confirm(`确定删除会话「${props.conversation.title}」吗？`, '删除确认', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await conversationStore.remove(props.conversation.id)
    ElMessage.success('已删除')
  } catch {
    /* 用户取消，无需处理 */
  }
}
</script>

<template>
  <li class="conv-item" :class="{ 'is-active': active }" @click="handleSelect">
    <span class="conv-item__icon">{{ conversation.icon }}</span>

    <input
      v-if="editing"
      ref="inputRef"
      v-model="draft"
      class="conv-item__input"
      @click.stop
      @keydown.enter.prevent="commitEdit"
      @keydown.esc="cancelEdit"
      @blur="commitEdit"
    />
    <span v-else class="conv-item__title text-ellipsis">{{ conversation.title }}</span>

    <span v-if="!editing" class="conv-item__actions" @click.stop>
      <el-icon class="conv-item__action" title="重命名" @click="startEdit"><Edit /></el-icon>
      <el-icon class="conv-item__action" title="导出" @click="handleDownload"><Download /></el-icon>
      <el-icon class="conv-item__action" title="删除" @click="handleDelete"><Delete /></el-icon>
    </span>
  </li>
</template>

<style lang="scss" scoped>
.conv-item {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 42px;
  padding: 0 10px;
  border-radius: var(--radius-control);
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: background-color 0.15s;

  &:hover {
    background: var(--color-hover);

    .conv-item__actions {
      display: flex;
    }
  }

  &.is-active {
    background: var(--color-brand-soft);
    color: var(--color-text);
  }

  &__icon {
    flex: none;
    width: 20px;
    font-size: 16px;
    text-align: center;
    line-height: 1;
  }

  &__title {
    flex: 1;
    min-width: 0;
    font-size: 14px;
  }

  &__input {
    flex: 1;
    min-width: 0;
    height: 26px;
    padding: 0 6px;
    border: 1px solid var(--color-brand);
    border-radius: 6px;
    background: #fff;
    font-size: 14px;
    color: var(--color-text);
    outline: none;
  }

  &__actions {
    display: none;
    flex: none;
    align-items: center;
    gap: 8px;
    color: var(--color-text-muted);
  }

  &__action {
    font-size: 15px;
    cursor: pointer;

    &:hover {
      color: var(--color-text);
    }
  }
}
</style>
