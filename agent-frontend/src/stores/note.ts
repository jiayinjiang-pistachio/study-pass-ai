import { ref } from 'vue'
import { defineStore } from 'pinia'
import type { Note } from '@/types/note'
import * as noteApi from '@/api/note'

export const useNoteStore = defineStore('note', () => {
  const notes = ref<Note[]>([])
  const activeNoteId = ref('')
  const loading = ref(false)

  function find(id: string): Note | undefined {
    return notes.value.find((item) => item.id === id)
  }

  async function load(): Promise<void> {
    loading.value = true
    try {
      const list = await noteApi.fetchNotes()
      notes.value = list
      if (!list.some((n) => n.id === activeNoteId.value)) {
        activeNoteId.value = list[0]?.id ?? ''
      }
    } finally {
      loading.value = false
    }
  }

  function select(id: string): void {
    activeNoteId.value = id
  }

  async function create(): Promise<void> {
    const note = await noteApi.createNote()
    notes.value.unshift(note)
    activeNoteId.value = note.id
  }

  async function rename(id: string, title: string): Promise<void> {
    const trimmed = title.trim()
    if (!trimmed) return
    const updated = await noteApi.renameNote(id, trimmed)
    const target = find(id)
    if (target) {
      target.title = updated.title
      target.updatedAt = updated.updatedAt
    }
  }

  async function saveContent(id: string, content: string): Promise<void> {
    const target = find(id)
    if (!target || target.content === content) return
    target.content = content
    const updated = await noteApi.saveNoteContent(id, content)
    target.updatedAt = updated.updatedAt
  }

  async function remove(id: string): Promise<void> {
    await noteApi.deleteNote(id)
    const index = notes.value.findIndex((item) => item.id === id)
    if (index === -1) return
    notes.value.splice(index, 1)
    if (activeNoteId.value === id) {
      const next = notes.value[index] ?? notes.value[index - 1]
      activeNoteId.value = next?.id ?? ''
    }
  }

  return { notes, activeNoteId, loading, load, select, create, rename, saveContent, remove }
})
