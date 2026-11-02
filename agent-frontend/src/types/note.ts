/** 侧栏统一展示图标（后端不返回图标） */
export const NOTE_ICON = '📝'

/** 笔记列表项：列表接口不返回正文 */
export interface NoteSummary {
  id: number
  sessionId: number
  noteType: string
  title: string
  tags: string[]
  /** 创建时间（毫秒） */
  createdAt: number
  /** 更新时间（毫秒） */
  updatedAt: number
}

export interface Note extends NoteSummary {
  /** 正文：后端存 Markdown，编辑器加载时按需转 HTML */
  content: string
}
