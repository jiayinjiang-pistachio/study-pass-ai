<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { ElMessage } from 'element-plus'
import SidebarItem from './SidebarItem.vue'
import { useNoteStore } from '@/stores/note'

const noteStore = useNoteStore()
const { notes, activeNoteId, loading } = storeToRefs(noteStore)

function handleExport(id: string): void {
  const target = notes.value.find((item) => item.id === id)
  ElMessage.info(`导出「${target?.title ?? ''}」功能开发中`)
}
</script>

<template>
  <ul v-loading="loading" class="sidebar-list scroll-area">
    <SidebarItem
      v-for="item in notes"
      :key="item.id"
      :id="item.id"
      :title="item.title"
      :icon="item.icon"
      :active="item.id === activeNoteId"
      entity-label="笔记"
      @select="noteStore.select"
      @rename="noteStore.rename"
      @remove="noteStore.remove"
      @export="handleExport"
    />
  </ul>
</template>
