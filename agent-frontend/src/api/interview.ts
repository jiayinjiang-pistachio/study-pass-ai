import { request } from './request'
import { normalizeVoiceRoom } from '@/utils/voiceInterview'
import type {
  InterviewBackground,
  InterviewConfirmPayload,
  InterviewConfirmResult,
  VoiceQaItem,
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

/** 挂断语音面试：提交前端整理的问答与时长 */
export interface VoiceFinishPayload {
  qaObject: VoiceQaItem[]
  interviewDuration: number
}

export interface VoiceFinishResult {
  interviewId: number
  sessionId: number
  status: number
  interviewDuration: number
  qaCount: number
}

interface RawVoiceFinishResult {
  interview_id?: number
  session_id?: number
  status?: number
  interview_duration?: number
  qa_count?: number
}

/**
 * 结束语音面试：POST /interviews/{interview_id}/voice/finish
 * 后端会停止 RTC AI，并保存 qa_object / interview_duration，置 status=1。
 */
export async function finishVoiceInterview(
  interviewId: number,
  payload: VoiceFinishPayload,
): Promise<VoiceFinishResult> {
  const data = await request<RawVoiceFinishResult>(
    `/interviews/${interviewId}/voice/finish`,
    {
      method: 'POST',
      body: {
        qa_object: payload.qaObject,
        interview_duration: payload.interviewDuration,
      },
    },
  )
  return {
    interviewId: data.interview_id ?? interviewId,
    sessionId: data.session_id ?? 0,
    status: data.status ?? 0,
    interviewDuration: data.interview_duration ?? payload.interviewDuration,
    qaCount: data.qa_count ?? payload.qaObject.length,
  }
}

interface RawConfirmResult {
  run_id?: string
  interview_id?: number
  session_id?: number
  message_id?: number
  voice?: unknown
}

function toConfirmBackground(background: InterviewBackground): Record<string, string> {
  return {
    target_job: background.targetJob,
    target_level: background.targetLevel,
    years_experience: background.yearsExperience,
    target_skills: background.targetSkills,
    project_experience: background.projectExperience,
    weak_topics: background.weakTopics,
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
    voice: normalizeVoiceRoom(data.voice),
  }
}
