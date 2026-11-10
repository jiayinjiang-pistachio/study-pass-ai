import type { AgentCapability } from '@/types/agent'
import type { ChatModule } from '@/types/conversation'
import { SESSION_MODE_BY_MODULE } from '@/types/conversation'
import { request } from './request'

interface RawCapability {
  name?: string
  title?: string
  kind?: string
  requires?: unknown
  returns?: string
  description?: string
}

function toCapability(raw: RawCapability): AgentCapability | null {
  if (typeof raw.name !== 'string' || !raw.name) return null
  const kind =
    raw.kind === 'chat' || raw.kind === 'workflow' || raw.kind === 'task'
      ? raw.kind
      : 'task'
  return {
    name: raw.name,
    title: raw.title ?? raw.name,
    kind,
    requires: Array.isArray(raw.requires)
      ? raw.requires.filter((item): item is string => typeof item === 'string')
      : [],
    returns: raw.returns ?? 'text',
    description: raw.description ?? '',
  }
}

/** 按房间拉取可用能力；能力接口失败时由调用方回退到静态按钮列表 */
export async function fetchAgentCapabilities(
  module: ChatModule,
): Promise<AgentCapability[]> {
  const data = await request<RawCapability[]>('/agent/capabilities', {
    params: { session_mode: SESSION_MODE_BY_MODULE[module] },
    silent: true,
  })
  if (!Array.isArray(data)) return []
  return data
    .map(toCapability)
    .filter((item): item is AgentCapability => item !== null)
}
