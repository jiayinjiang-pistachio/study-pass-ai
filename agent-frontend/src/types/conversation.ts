export const ModuleKey = {
  Study: 'study',
  Interview: 'interview',
  Note: 'note',
} as const
export type ModuleKey = (typeof ModuleKey)[keyof typeof ModuleKey]

/** 走会话列表的模块（笔记模块使用独立的笔记数据源） */
export type ChatModule = Extract<ModuleKey, 'study' | 'interview'>

/** 前端模块 → 后端 sessions.session_mode */
export const SESSION_MODE_BY_MODULE: Record<ChatModule, 0 | 1> = {
  [ModuleKey.Study]: 0,
  [ModuleKey.Interview]: 1,
}

/** 后端未返回图标，按模块给出稳定的展示图标 */
export const MODULE_ICONS: Record<ChatModule, string> = {
  [ModuleKey.Study]: '📘',
  [ModuleKey.Interview]: '💻',
}

export interface Conversation {
  id: number
  title: string
  icon: string
  module: ChatModule
  /** 创建时间（毫秒） */
  createdAt: number
}

export const MODULE_LABELS: Record<ModuleKey, string> = {
  study: '学习室',
  interview: '面试间',
  note: '笔记本',
}
