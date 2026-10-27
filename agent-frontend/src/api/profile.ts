import { ApiError, request } from './request'

/** 用户求职画像：后端出参裁剪后的基础资料 */
export interface UserProfile {
  targetJob: string | null
  yearsExperience: number | null
  targetLevel: string | null
  targetSkills: string[]
  weakTopics: string[]
}

/** 写入画像的请求体（后端使用 snake_case 字段名） */
export interface ProfilePayload {
  target_job: string
  years_experience: number
  target_level: string
  target_skills: string[]
  weak_topics: string[]
}

interface RawProfile {
  target_job?: string | null
  years_experience?: number | null
  target_level?: string | null
  target_skills?: string[] | null
  weak_topics?: string[] | null
}

function toProfile(raw: RawProfile): UserProfile {
  return {
    targetJob: raw.target_job ?? null,
    yearsExperience:
      typeof raw.years_experience === 'number' ? raw.years_experience : null,
    targetLevel: raw.target_level ?? null,
    targetSkills: Array.isArray(raw.target_skills) ? raw.target_skills : [],
    weakTopics: Array.isArray(raw.weak_topics) ? raw.weak_topics : [],
  }
}

/**
 * 查询当前用户画像；未创建时后端返回 404，这里归一为 null。
 * 用 silent 关闭全局提示：资料未填写是正常状态，不应弹错误。
 */
export async function fetchMyProfile(): Promise<UserProfile | null> {
  try {
    const data = await request<RawProfile>('/profiles/me', { silent: true })
    return toProfile(data)
  } catch (error) {
    if (error instanceof ApiError && error.code === 404) return null
    throw error
  }
}

export function createProfile(payload: ProfilePayload): Promise<UserProfile> {
  return request<RawProfile>('/profiles', {
    method: 'POST',
    body: payload,
  }).then(toProfile)
}

export function updateProfile(payload: ProfilePayload): Promise<UserProfile> {
  return request<RawProfile>('/profiles/me', {
    method: 'PUT',
    body: payload,
  }).then(toProfile)
}
