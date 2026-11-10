import type { ChatModule } from '@/types/conversation'

/** 智能体标识：须与后端 app/agent/registry.py 的能力名保持一致 */
export const AgentName = {
  Quiz: 'quiz_generate_workflow',
  Difficulty: 'difficulty_learner',
  Note: 'note_archiver',
  InterviewHost: 'interview_host',
  InterviewEvaluator: 'interview_evaluator',
} as const
export type AgentName = (typeof AgentName)[keyof typeof AgentName]

export interface AgentOption {
  name: string
  label: string
}

/** 后端 GET /agent/capabilities 下发的能力描述 */
export interface AgentCapability {
  name: string
  title: string
  kind: 'chat' | 'workflow' | 'task'
  requires: string[]
  returns: string
  description: string
}

/**
 * 输入框底部的智能体按钮，按房间区分。
 * 按钮只是一次性的 `preferred_agent` 提示：发送后即清除，
 * 未选择时由后端总控根据关键词 / 语义 / 规划决定能力。
 *
 * 该常量仅作为能力接口不可用时的兜底；正常流程由 `stores/agent.ts`
 * 拉取后端能力列表并过滤出任务类能力。
 */
export const AGENTS_BY_MODULE: Record<ChatModule, AgentOption[]> = {
  study: [
    { name: AgentName.Quiz, label: '出题测评' },
    { name: AgentName.Difficulty, label: '难点学习' },
    { name: AgentName.Note, label: '笔记归档' },
  ],
  interview: [
    { name: AgentName.InterviewHost, label: '面试主考官' },
    { name: AgentName.InterviewEvaluator, label: '面试复盘' },
    { name: AgentName.Difficulty, label: '难点学习' },
    { name: AgentName.Note, label: '笔记归档' },
  ],
}
