import axios from 'axios'
import type { AxiosError, AxiosResponse } from 'axios'
import { ElMessage } from 'element-plus'
import router from '@/router'
import { clearTokens, getAccessToken, getRefreshToken, setTokens } from '@/utils/token'

const API_PREFIX = import.meta.env.VITE_API_PREFIX || '/api'
const REQUEST_TIMEOUT = 15000
/** 这些接口本身用于建立会话，不参与 401 自动续期 */
const AUTH_FREE_PATHS = ['/auth/login', '/auth/register', '/auth/refresh']

declare module 'axios' {
  export interface AxiosRequestConfig {
    /** 跳过 Authorization 注入与 401 续期（登录、注册、刷新令牌） */
    skipAuth?: boolean
    /** 关闭请求层统一错误提示，由调用方自行处理 */
    silent?: boolean
    /** 内部标记：401 后是否已重试过，避免刷新失败时死循环 */
    _retry?: boolean
  }
}

/** 后端统一响应结构 */
export interface ApiEnvelope<T> {
  code: number
  message: string
  detail?: string | null
  data: T
}

export class ApiError extends Error {
  code: number
  detail?: string | null

  constructor(message: string, code: number, detail?: string | null) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.detail = detail
  }
}

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'DELETE'

export interface RequestOptions {
  method?: HttpMethod
  body?: unknown
  /** 是否自动携带令牌并处理 401 续期，默认开启 */
  auth?: boolean
  /** 是否关闭全局错误提示（调用方自行处理时使用） */
  silent?: boolean
}

interface TokenPairResponse {
  access_token: string
  refresh_token: string
}

/**
 * Mock.js 通过替换全局 XMLHttpRequest 实现请求拦截，因此这里固定使用 xhr 适配器。
 * 不要改成 fetch 适配器，否则开发期 Mock 会失效。
 */
const http = axios.create({
  baseURL: API_PREFIX,
  timeout: REQUEST_TIMEOUT,
  adapter: 'xhr',
})

function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error
  if (!axios.isAxiosError(error)) return new ApiError('请求失败', -1)

  const status = error.response?.status
  const payload = error.response?.data as Partial<ApiEnvelope<unknown>> | undefined
  if (payload && typeof payload === 'object') {
    return new ApiError(
      payload.message || `请求失败（${status ?? '未知'}）`,
      payload.code ?? status ?? -1,
      payload.detail,
    )
  }
  if (error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT') {
    return new ApiError('请求超时', -2)
  }
  if (status) {
    return new ApiError(`请求失败（${status}）`, status)
  }
  return new ApiError('网络异常，请稍后重试', -1)
}

let lastToast = { message: '', at: 0 }

/** 全局错误提示：相同文案在短时间内只弹一次，避免并发请求刷屏 */
function notifyError(message: string): void {
  const now = Date.now()
  if (message === lastToast.message && now - lastToast.at < 1500) return
  lastToast = { message, at: now }
  ElMessage.error(message)
}

let redirectingToLogin = false

function redirectToLogin(): void {
  if (redirectingToLogin) return
  const current = router.currentRoute.value
  if (current.name === 'login') return

  redirectingToLogin = true
  void router
    .replace({
      name: 'login',
      query: current.fullPath === '/' ? {} : { redirect: current.fullPath },
    })
    .finally(() => {
      redirectingToLogin = false
    })
}

function handleAuthExpired(message: string): void {
  clearTokens()
  notifyError(message)
  redirectToLogin()
}

let refreshPromise: Promise<string> | null = null

/** 刷新令牌去重：并发 401 只发起一次刷新，其余请求等待同一个结果 */
function refreshAccessToken(): Promise<string> {
  if (!refreshPromise) {
    refreshPromise = (async () => {
      const refreshToken = getRefreshToken()
      if (!refreshToken) {
        throw new ApiError('登录状态已失效', 401)
      }

      const response = await http.post<
        ApiEnvelope<TokenPairResponse>,
        AxiosResponse<TokenPairResponse>
      >(
        '/auth/refresh',
        { refresh_token: refreshToken },
        { skipAuth: true, silent: true },
      )
      const tokens = response.data
      setTokens(tokens.access_token, tokens.refresh_token)
      return tokens.access_token
    })().finally(() => {
      refreshPromise = null
    })
  }
  return refreshPromise
}

// 请求拦截：受保护接口自动携带访问令牌
http.interceptors.request.use((config) => {
  if (!config.skipAuth) {
    const accessToken = getAccessToken()
    if (accessToken) {
      config.headers.set('Authorization', `Bearer ${accessToken}`)
    }
  }
  return config
})

// 响应拦截：解包信封；401 时刷新令牌并重试一次；其余错误统一提示
http.interceptors.response.use(
  (response) => {
    const envelope = response.data as ApiEnvelope<unknown> | null
    if (!envelope || envelope.code !== 200) {
      const apiError = new ApiError(
        envelope?.message || '请求失败',
        envelope?.code ?? response.status,
        envelope?.detail,
      )
      if (!response.config.silent) notifyError(apiError.message)
      return Promise.reject(apiError)
    }
    response.data = envelope.data
    return response
  },
  async (error: AxiosError) => {
    const config = error.config
    const status = error.response?.status
    const apiError = toApiError(error)

    if (status === 401 && config && !config.skipAuth) {
      if (config._retry) {
        handleAuthExpired('登录状态已过期，请重新登录')
        return Promise.reject(apiError)
      }
      config._retry = true

      if (!getRefreshToken()) {
        handleAuthExpired('登录状态已失效，请重新登录')
        return Promise.reject(apiError)
      }

      let newAccessToken: string
      try {
        newAccessToken = await refreshAccessToken()
      } catch (refreshError) {
        const refreshApiError = toApiError(refreshError)
        handleAuthExpired(
          refreshApiError.code === 401 ? '登录状态已过期，请重新登录' : refreshApiError.message,
        )
        return Promise.reject(refreshApiError)
      }

      config.headers.set('Authorization', `Bearer ${newAccessToken}`)
      return http.request(config)
    }

    if (!config?.silent) notifyError(apiError.message)
    return Promise.reject(apiError)
  },
)

/**
 * 统一请求入口：解包信封并返回业务数据。
 *
 * 受保护接口自动携带 Authorization；401 时刷新令牌并重试一次，刷新失败则
 * 清理本地令牌并跳转登录页。
 */
export async function request<T>(url: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, auth = true, silent = false } = options
  const skipAuth = !auth || AUTH_FREE_PATHS.some((path) => url.startsWith(path))

  const response = await http.request<ApiEnvelope<T>, AxiosResponse<T>>({
    url,
    method,
    data: body,
    skipAuth,
    silent,
  })
  return response.data
}
