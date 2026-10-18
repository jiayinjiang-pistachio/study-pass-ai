import { computed } from 'vue'
import type { ComputedRef } from 'vue'
import { useRoute } from 'vue-router'
import type { ModuleKey } from '@/types/conversation'
import { ModuleKey as Module } from '@/types/conversation'

/**
 * 当前模块（学习室 / 面试间 / 笔记本）的唯一事实来源是路由 name。
 * 各组件通过本 composable 派生，避免在 store 或本地状态里再存一份。
 */
export function useCurrentModule(): ComputedRef<ModuleKey> {
  const route = useRoute()
  return computed(() => (route.name as ModuleKey | undefined) ?? Module.Interview)
}
