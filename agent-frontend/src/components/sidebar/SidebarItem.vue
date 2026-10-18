<script setup lang="ts">
import { nextTick, ref } from 'vue'
import { Delete, Download, Edit } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

/**
 * 侧栏列表项（会话 / 笔记共用）。
 * 只负责展示与交互，具体的数据操作由父组件监听事件后调用对应 store。
 */
const props = defineProps<{
  id: string
  title: string
  icon: string
  active: boolean
  /** 用于删除确认文案，如「会话」「笔记」 */
  entityLabel: string
}>()

const emit = defineEmits<{
  select: [id: string]
  rename: [id: string, title: string]
  remove: [id: string]
  export: [id: string]
}>()

const editing = ref(false)
const draft = ref('')
const inputRef = ref<HTMLInputElement | null>(null)

function handleSelect(): void {
  if (editing.value) return
  emit('select', props.id)
}

async function startEdit(): Promise<void> {
  editing.value = true
  draft.value = props.title
  await nextTick()
  inputRef.value?.focus()
  inputRef.value?.select()
}

function commitEdit(): void {
  if (!editing.value) return
  editing.value = false
  emit('rename', props.id, draft.value)
}

function cancelEdit(): void {
  editing.value = false
}

async function handleRemove(): Promise<void> {
  try {
    await ElMessageBox.confirm(`确定删除${props.entityLabel}「${props.title}」吗？`, '删除确认', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
    emit('remove', props.id)
    ElMessage.success('已删除')
  } catch {
    /* 用户取消，无需处理 */
  }
}
</script>

<template>
  <li class="sidebar-item" :class="{ 'is-active': active }" @click="handleSelect">
    <span class="sidebar-item__icon">{{ icon }}</span>

    <input
      v-if="editing"
      ref="inputRef"
      v-model="draft"
      class="sidebar-item__input"
      @click.stop
      @keydown.enter.prevent="commitEdit"
      @keydown.esc="cancelEdit"
      @blur="commitEdit"
    />
    <span v-else class="sidebar-item__title text-ellipsis">{{ title }}</span>

    <span v-if="!editing" class="sidebar-item__actions" @click.stop>
      <el-icon class="sidebar-item__action" title="重命名" @click="startEdit"><Edit /></el-icon>
      <el-icon class="sidebar-item__action" title="导出" @click="emit('export', id)">
        <Download />
      </el-icon>
      <el-icon class="sidebar-item__action" title="删除" @click="handleRemove"><Delete /></el-icon>
    </span>
  </li>
</template>

<style lang="scss" scoped>
.sidebar-item {
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

    .sidebar-item__actions {
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
