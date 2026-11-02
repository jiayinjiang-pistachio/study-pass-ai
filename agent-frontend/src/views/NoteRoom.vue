<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { ElMessage, ElMessageBox } from 'element-plus'
import EmptyState from '@/components/common/EmptyState.vue'
import NotebookEditor from '@/components/note/NotebookEditor.vue'
import { useNoteStore } from '@/stores/note'

const noteStore = useNoteStore()
const { activeNote, loading, saving, dirty, draftTitle, draftContent } = storeToRefs(noteStore)

async function handleSave(): Promise<void> {
  try {
    await noteStore.saveActiveNote()
    if (!noteStore.dirty) ElMessage.success('已保存')
  } catch {
    /* 错误提示由请求层统一处理 */
  }
}

async function handleDelete(): Promise<void> {
  const note = activeNote.value
  if (!note) return
  try {
    await ElMessageBox.confirm(`确定删除笔记「${note.title}」吗？`, '删除确认', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await noteStore.remove(note.id)
    ElMessage.success('已删除')
  } catch {
    /* 用户取消或删除失败，错误提示由请求层统一处理 */
  }
}

onMounted(() => {
  void noteStore.ensureLoaded()
})

onBeforeUnmount(() => {
  void noteStore.flushSave().catch(() => {
    /* 错误提示由请求层统一处理 */
  })
})
</script>

<template>
  <div v-loading="loading" class="note-room">
    <NotebookEditor
      v-if="activeNote"
      v-model:title="draftTitle"
      v-model:content="draftContent"
      :saving="saving"
      :dirty="dirty"
      @save="handleSave"
      @delete="handleDelete"
      @content-synced="noteStore.syncEditorContent"
    />
    <EmptyState v-else-if="!loading" description="暂无笔记，点击左侧「新建笔记」开始记录" />
  </div>
</template>

<style lang="scss" scoped>
.note-room {
  flex: 1;
  min-height: 0;
  display: flex;
  justify-content: center;
  padding: 28px 24px;
  overflow: hidden;
}
</style>
