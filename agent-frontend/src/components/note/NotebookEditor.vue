<script setup lang="ts">
import { onBeforeUnmount, shallowRef, watch } from 'vue'
import { Delete } from '@element-plus/icons-vue'
import '@wangeditor-next/editor/dist/css/style.css'
import { Editor, Toolbar } from '@wangeditor-next/editor-for-vue'
import type { IDomEditor, IEditorConfig, IToolbarConfig } from '@wangeditor-next/editor'

const title = defineModel<string>('title', { required: true })
const content = defineModel<string>('content', { required: true })

defineProps<{
  saving: boolean
  dirty: boolean
}>()

const emit = defineEmits<{
  save: []
  delete: []
  /** 外部切换文档后编辑器回写的规范化 HTML，交给调用方同步保存基线 */
  contentSynced: [value: string]
}>()

const editorRef = shallowRef<IDomEditor>()

/** 最近一次由编辑器自身写出的内容，用于区分「外部切换」与「用户输入」 */
let lastEmitted = ''
/** 外部内容写入编辑器后，等待编辑器回写一次规范化结果 */
let awaitingSync = false
let syncTimer: ReturnType<typeof setTimeout> | undefined

watch(content, (value) => {
  if (value === lastEmitted) return
  awaitingSync = true
  if (syncTimer) clearTimeout(syncTimer)
  syncTimer = setTimeout(() => {
    awaitingSync = false
  }, 300)
})

function handleContentUpdate(value: string): void {
  if (awaitingSync) {
    awaitingSync = false
    if (syncTimer) clearTimeout(syncTimer)
    // 记下这次回写，调用方同步草稿后不应再次触发等待
    lastEmitted = value
    emit('contentSynced', value)
    return
  }
  lastEmitted = value
  content.value = value
}

const toolbarConfig: Partial<IToolbarConfig> = {
  toolbarKeys: [
    'bold',
    'italic',
    'underline',
    'bulletedList',
    'numberedList',
    'indent',
    'delIndent',
    '|',
    'insertLink',
    'insertImage',
  ],
}

const editorConfig: Partial<IEditorConfig> = {
  placeholder: '开始记录你的学习笔记…',
}

function handleCreated(editor: IDomEditor): void {
  editorRef.value = editor
}

onBeforeUnmount(() => {
  if (syncTimer) clearTimeout(syncTimer)
  editorRef.value?.destroy()
})
</script>

<template>
  <div class="notebook-editor">
    <div class="notebook-editor__toolbar">
      <Toolbar
        class="notebook-editor__toolbar-bar"
        :editor="editorRef"
        :default-config="toolbarConfig"
        mode="default"
      />
      <div class="notebook-editor__actions">
        <el-button
          size="small"
          type="primary"
          :loading="saving"
          :disabled="!dirty && !saving"
          @click="emit('save')"
        >
          保存
        </el-button>
        <button type="button" class="notebook-editor__delete" title="删除笔记" @click="emit('delete')">
          <el-icon><Delete /></el-icon>
        </button>
      </div>
    </div>

    <input v-model="title" class="notebook-editor__title" type="text" placeholder="笔记标题" />

    <div class="notebook-editor__body">
      <Editor
        :model-value="content"
        class="notebook-editor__content"
        :default-config="editorConfig"
        mode="default"
        @update:model-value="handleContentUpdate"
        @onCreated="handleCreated"
      />
    </div>
  </div>
</template>

<style lang="scss" scoped>
.notebook-editor {
  display: flex;
  flex-direction: column;
  width: 100%;
  max-width: var(--editor-max-width);
  height: 100%;
  min-height: 0;
  background: var(--color-surface);
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
  overflow: hidden;

  &__toolbar {
    flex: none;
    display: flex;
    align-items: center;
    border-bottom: 1px solid var(--color-divider);
  }

  &__toolbar-bar {
    flex: 1;
    min-width: 0;
  }

  &__actions {
    flex: none;
    display: flex;
    align-items: center;
    gap: 8px;
    padding-right: 8px;
  }

  &__delete {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    border: none;
    background: transparent;
    color: var(--color-text-muted);
    font-size: 18px;
    cursor: pointer;
    transition: color 0.2s;

    &:hover {
      color: var(--color-text);
    }
  }

  &__title {
    flex: none;
    width: 100%;
    padding: 20px 24px 14px;
    border: none;
    border-bottom: 1px solid var(--color-divider);
    outline: none;
    background: transparent;
    font-family: inherit;
    font-size: 20px;
    font-weight: 700;
    color: var(--color-text);
    text-align: center;

    &::placeholder {
      font-weight: 400;
      color: var(--color-text-muted);
    }
  }

  &__body {
    flex: 1;
    min-height: 0;
  }

  /* 让编辑区在卡片内撑满并独立滚动 */
  &__body :deep(.w-e-text-container) {
    height: 100%;
  }

  &__body :deep(.w-e-scroll) {
    height: 100%;
    overflow-y: auto;
  }
}
</style>
