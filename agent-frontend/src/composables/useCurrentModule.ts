import { computed } from 'vue'
import type { ComputedRef } from 'vue'
import { useRoute } from 'vue-router'
import type { ChatModule, ModuleKey } from '@/types/conversation'
import { ModuleKey as Module } from '@/types/conversation'

/**
 * 当前模块（学习室 / 面试间 / 笔记本）的唯一事实来源是路由 name。
 * 各组件通过本 composable 派生，避免在 store 或本地状态里再存一份。
 */
export function useCurrentModule(): ComputedRef<ModuleKey> {
  const route = useRoute()
  return computed(() => (route.name as ModuleKey | undefined) ?? Module.Interview)
}

/** 当前模块若为会话模块（学习室 / 面试间）则返回，笔记本返回 null */
export function useCurrentChatModule(): ComputedRef<ChatModule | null> {
  const module = useCurrentModule()
  return computed(() =>
    module.value === Module.Note ? null : module.value,
  )
}
