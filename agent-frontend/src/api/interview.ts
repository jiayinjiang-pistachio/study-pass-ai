import { request } from './request'

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
