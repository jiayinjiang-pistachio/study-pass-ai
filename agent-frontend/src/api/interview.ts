import { request } from './request'
import type {
  InterviewBackground,
  InterviewConfirmPayload,
  InterviewConfirmResult,
} from '@/types/chat'

/** 面试问答明细；字段按容错处理，展示时允许缺失 */
export interface InterviewQa {
  id?: number | string
  question?: string
  answer?: string
  created_at?: number | string
}

export interface InterviewDetail {
  id: number
  session_id: number
  message_id: number
  qa_object: InterviewQa[]
  interview_duration: number
  status: number
  created_at: number
  updated_at: number
}

/** 获取面试详情（后端按 interview_id + 当前用户校验） */
export function fetchInterview(interviewId: number): Promise<InterviewDetail> {
  return request<InterviewDetail>(`/interviews/${interviewId}`)
}

interface RawConfirmResult {
  run_id?: string
  interview_id?: number
  session_id?: number
  message_id?: number
}

function toConfirmBackground(background: InterviewBackground): Record<string, string> {
  return {
    target_job: background.targetJob,
    target_level: background.targetLevel,
    years_experience: background.yearsExperience,
    target_skills: background.targetSkills,
    project_experience: background.projectExperience,
    weak_topics: background.weakTopics,
    opening_question: background.openingQuestion,
  }
}

/** 确认面试背景并创建正式面试：POST /interviews/confirm */
export async function confirmInterview(
  payload: InterviewConfirmPayload,
): Promise<InterviewConfirmResult> {
  const data = await request<RawConfirmResult>('/interviews/confirm', {
    method: 'POST',
    body: {
      run_id: payload.runId,
      background: toConfirmBackground(payload.background),
    },
  })
  return {
    runId: typeof data.run_id === 'string' ? data.run_id : payload.runId,
    interviewId: data.interview_id ?? 0,
    sessionId: data.session_id ?? 0,
    messageId: data.message_id ?? 0,
  }
}
