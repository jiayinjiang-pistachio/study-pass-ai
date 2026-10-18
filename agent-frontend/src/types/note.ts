export interface Note {
  id: string
  title: string
  icon: string
  /** 富文本 HTML 内容 */
  content: string
  updatedAt: number
}
