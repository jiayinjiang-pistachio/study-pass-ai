import type { ChatModule } from '@/types/conversation'

/** 智能体标识：须与后端 CHAT_AGENT_NAMES / WORKFLOW_ROUTE_RULES 保持一致 */
export const AgentName = {
  Quiz: 'quiz_generate_workflow',
  Difficulty: 'difficulty_learner',
  Note: 'note_archiver',
  InterviewHost: 'interview_host',
  InterviewJudge: 'interview_evaluator',
} as const
export type AgentName = (typeof AgentName)[keyof typeof AgentName]

export interface AgentOption {
  name: AgentName
  label: string
}

/** 输入框底部的智能体按钮，按房间区分 */
export const AGENTS_BY_MODULE: Record<ChatModule, AgentOption[]> = {
  study: [
    { name: AgentName.Quiz, label: '出题测评' },
    { name: AgentName.Difficulty, label: '难点学习' },
    { name: AgentName.Note, label: '笔记归档' },
  ],
  interview: [
    { name: AgentName.InterviewHost, label: '面试主考官' },
    { name: AgentName.InterviewJudge, label: '面试评测' },
    { name: AgentName.Difficulty, label: '难点学习' },
    { name: AgentName.Note, label: '笔记归档' },
  ],
}

/** 未显式选择时按房间使用默认智能体，保证所有消息都走总控接口 */
export const DEFAULT_AGENT_BY_MODULE: Record<ChatModule, AgentName> = {
  study: AgentName.Quiz,
  interview: AgentName.InterviewHost,
}
