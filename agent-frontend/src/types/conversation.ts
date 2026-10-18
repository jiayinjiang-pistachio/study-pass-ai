export const ModuleKey = {
  Study: 'study',
  Interview: 'interview',
  Note: 'note',
} as const
export type ModuleKey = (typeof ModuleKey)[keyof typeof ModuleKey]

export interface Conversation {
  id: string
  title: string
  icon: string
  module: ModuleKey
  updatedAt: number
}

export const MODULE_LABELS: Record<ModuleKey, string> = {
  study: '学习室',
  interview: '面试间',
  note: '笔记本',
}
