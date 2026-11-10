import { ref } from 'vue'
import { defineStore } from 'pinia'
import type { ChatModule } from '@/types/conversation'
import { AGENTS_BY_MODULE } from '@/types/agent'
import type { AgentOption } from '@/types/agent'
import { fetchAgentCapabilities } from '@/api/agent'

/**
 * 输入框智能体选择：按房间各记一份，切换模块时不串用。
 * 选择是「一次性提示」，发送时由 consume() 取出并清空；
 * 未选择时不回落到默认能力，交给后端总控自行判断。
 *
 * 快捷按钮以后端能力接口为准，只展示任务类能力；
 * 接口失败或尚未加载时用 AGENTS_BY_MODULE 静态兜底。
 */
export const useAgentStore = defineStore('agent', () => {
  const selectedByModule = ref<Record<ChatModule, string | null>>({
    study: null,
    interview: null,
  })
  /** 房间 -> 已拉取的任务能力按钮；未拉取前为 null */
  const optionsByModule = ref<Record<ChatModule, AgentOption[] | null>>({
    study: null,
    interview: null,
  })
  const loadingByModule = ref<Record<ChatModule, boolean>>({
    study: false,
    interview: false,
  })

  function toggle(module: ChatModule, agent: string): void {
    selectedByModule.value[module] =
      selectedByModule.value[module] === agent ? null : agent
  }

  /** 取出并清空当前房间的选择；未选择返回 null。 */
  function consume(module: ChatModule): string | null {
    const selected = selectedByModule.value[module]
    if (selected === null) return null
    selectedByModule.value[module] = null
    return selected
  }

  /** 当前房间可用的快捷按钮：优先能力接口，兜底静态配置 */
  function optionsFor(module: ChatModule): AgentOption[] {
    return optionsByModule.value[module] ?? AGENTS_BY_MODULE[module]
  }

  /** 拉取后端能力并映射为按钮；失败保持静态兜底，不打扰用户 */
  async function loadCapabilities(module: ChatModule): Promise<void> {
    if (loadingByModule.value[module] || optionsByModule.value[module]) return
    loadingByModule.value[module] = true
    try {
      const capabilities = await fetchAgentCapabilities(module)
      const options = capabilities
        .filter((capability) => capability.kind !== 'chat')
        .map((capability) => ({
          name: capability.name,
          label: capability.title,
        }))
      if (options.length) optionsByModule.value[module] = options
    } catch {
      // 能力接口不可用：保留 AGENTS_BY_MODULE 静态按钮
    } finally {
      loadingByModule.value[module] = false
    }
  }

  function reset(): void {
    selectedByModule.value = { study: null, interview: null }
    optionsByModule.value = { study: null, interview: null }
    loadingByModule.value = { study: false, interview: false }
  }

  return {
    selectedByModule,
    optionsByModule,
    loadingByModule,
    toggle,
    consume,
    optionsFor,
    loadCapabilities,
    reset,
  }
})
