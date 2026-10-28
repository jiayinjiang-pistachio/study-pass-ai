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

/** 回答参考的知识片段：原文由后端按 chunk_id 回查，已删除时为提示文案 */
export interface MessageSource {
  chunkId: string
  resourceId: number | null
  chunkIndex: number | null
  fileName: string
  /** 检索相似度（0~1），缺失时为 null */
  score: number | null
  text: string
}

export interface ChatMessage {
  id: number
  requestText: string
  responseText: string
  requestSegments: MessageSegment[]
  responseSegments: MessageSegment[]
  /** RAG 参考来源；未检索或未命中为空数组 */
  sources: MessageSource[]
  /** 0=生成中，1=完成，2=失败 */
  status: 0 | 1 | 2
  interviewId: number | null
  /** 创建时间（毫秒） */
  createdAt: number
}
