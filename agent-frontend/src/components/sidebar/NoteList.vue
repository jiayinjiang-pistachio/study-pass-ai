<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { ElMessage } from 'element-plus'
import SidebarItem from './SidebarItem.vue'
import { useNoteStore } from '@/stores/note'
import { NOTE_ICON } from '@/types/note'

const noteStore = useNoteStore()
const { noteList, activeNoteId, loading } = storeToRefs(noteStore)

function handleSelect(id: string | number): void {
  void noteStore.select(Number(id)).catch(() => {
    /* 错误提示由请求层统一处理 */
  })
}

function handleRename(id: string | number, title: string): void {
  void noteStore.rename(Number(id), title).catch(() => {
    /* 错误提示由请求层统一处理 */
  })
}

async function handleRemove(id: string | number): Promise<void> {
  try {
    await noteStore.remove(Number(id))
  } catch {
    /* 错误提示由请求层统一处理 */
  }
}

function handleExport(id: string | number): void {
  const target = noteList.value.find((item) => item.id === Number(id))
  ElMessage.info(`导出「${target?.title ?? ''}」功能开发中`)
}
</script>

<template>
  <ul v-loading="loading" class="sidebar-list scroll-area">
    <SidebarItem
      v-for="item in noteList"
      :key="item.id"
      :id="item.id"
      :title="item.title"
      :icon="NOTE_ICON"
      :active="item.id === activeNoteId"
      entity-label="笔记"
      @select="handleSelect"
      @rename="handleRename"
      @remove="handleRemove"
      @export="handleExport"
    />
  </ul>
</template>
