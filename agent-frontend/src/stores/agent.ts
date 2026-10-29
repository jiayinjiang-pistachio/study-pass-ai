import { ref } from 'vue'
import { defineStore } from 'pinia'
import type { ChatModule } from '@/types/conversation'
import { DEFAULT_AGENT_BY_MODULE } from '@/types/agent'
import type { AgentName } from '@/types/agent'

/**
 * 输入框智能体选择：按房间各记一份，切换模块时不串用。
 * 未选择时由 effective() 回落到房间默认智能体。
 */
export const useAgentStore = defineStore('agent', () => {
  const selectedByModule = ref<Record<ChatModule, AgentName | null>>({
    study: null,
    interview: null,
  })

  function toggle(module: ChatModule, agent: AgentName): void {
    selectedByModule.value[module] =
      selectedByModule.value[module] === agent ? null : agent
  }

  function effective(module: ChatModule): AgentName {
    return selectedByModule.value[module] ?? DEFAULT_AGENT_BY_MODULE[module]
  }

  function reset(): void {
    selectedByModule.value = { study: null, interview: null }
  }

  return { selectedByModule, toggle, effective, reset }
})
