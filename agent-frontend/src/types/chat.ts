export const SegmentType = {
  File: 'file',
  Image: 'image',
  Audio: 'audio',
} as const
export type SegmentType = (typeof SegmentType)[keyof typeof SegmentType]

/** 附件段：后端字段可能为 name / file_name，统一在接口层归一为 name */
export interface MessageSegment {
  type: SegmentType
  resourceId: number
  name: string
  url: string
}

export interface ChatMessage {
  id: number
  requestText: string
  responseText: string
  requestSegments: MessageSegment[]
  responseSegments: MessageSegment[]
  /** 0=生成中，1=完成，2=失败 */
  status: 0 | 1 | 2
  interviewId: number | null
  /** 创建时间（毫秒） */
  createdAt: number
}
