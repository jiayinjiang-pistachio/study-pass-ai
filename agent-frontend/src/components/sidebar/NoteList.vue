<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { ElMessage } from 'element-plus'
import SidebarItem from './SidebarItem.vue'
import { useNoteStore } from '@/stores/note'

const noteStore = useNoteStore()
const { notes, activeNoteId, loading } = storeToRefs(noteStore)

function handleSelect(id: string | number): void {
  noteStore.select(String(id))
}

function handleRename(id: string | number, title: string): void {
  void noteStore.rename(String(id), title)
}

async function handleRemove(id: string | number): Promise<void> {
  await noteStore.remove(String(id))
}

function handleExport(id: string | number): void {
  const key = String(id)
  const target = notes.value.find((item) => item.id === key)
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
      @select="handleSelect"
      @rename="handleRename"
      @remove="handleRemove"
      @export="handleExport"
    />
  </ul>
</template>
