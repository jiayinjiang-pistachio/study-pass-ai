import type { QuizQuestion } from '@/types/quiz'

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

/**
 * 面试背景：阶段式面试确认的可编辑字段，统一为字符串。
 * 字段由后端第一阶段根据简历 / 用户资料提取，前端只负责展示与编辑。
 */
export interface InterviewBackground {
  targetJob: string
  targetLevel: string
  yearsExperience: string
  targetSkills: string
  projectExperience: string
  weakTopics: string
  openingQuestion: string
}

/** 第一阶段待确认任务：强制走 JSON 分支，不直接流式输出 */
export interface InterviewPrepareData {
  runId: string
  sessionId: number
  resumeFileName: string
  background: InterviewBackground
}

/** 第二阶段提交体：run_id + 用户编辑后的背景 */
export interface InterviewConfirmPayload {
  runId: string
  background: InterviewBackground
}

/**
 * RTC 语音面试入房参数：全部以后端返回为准，前端不得写死。
 * token 只放 history state，不进入 URL。
 */
export interface VoiceRoom {
  appId: string
  roomId: string
  /** 当前用户 ID（用于识别字幕中的「我」） */
  userId: string
  /** AI 面试官 Bot ID（用于识别字幕中的「AI」） */
  botId: string
  rtcToken: string
  taskId: string
  /** token 过期时间（epoch 秒），缺失时为 null */
  expireAt: number | null
  /** AI 面试官是否已成功拉起；false 时前端不应入房 */
  started: boolean
}

/** 语音面试问答明细：挂断时提交给后端，并用于面试详情展示 */
export interface VoiceQaItem {
  id: number
  question: string
  answer: string
  /** 生成时间（epoch 秒） */
  created_at: number
}

/** 第二阶段返回体：面试已正式创建，可用于刷新会话 / 进入语音面试 */
export interface InterviewConfirmResult {
  runId: string
  interviewId: number
  sessionId: number
  messageId: number
  voice: VoiceRoom | null
}

export interface ChatMessage {
  id: number
  /** 后端 request_id：测评题目为 "{run_id}:quiz"，普通聊天可为 null */
  requestId: string | null
  requestText: string
  responseText: string
  requestSegments: MessageSegment[]
  responseSegments: MessageSegment[]
  /** RAG 参考来源；未检索或未命中为空数组 */
  sources: MessageSource[]
  /** 0=生成中，1=完成，2=失败 */
  status: 0 | 1 | 2
  /** 测评题目数组（后端已归一化）；非测评消息或评分后为 null */
  responsePayload: QuizQuestion[] | null
  /** 结构化载荷类型：知识卡为 knowledge_card，其余为 null */
  payloadType: 'knowledge_card' | null
  /** 仅本地临时消息使用：生成中的文案提示（如知识卡 + 播客） */
  loadingHint?: string
  interviewId: number | null
  /** 创建时间（毫秒） */
  createdAt: number
}
