import { ElMessage } from 'element-plus'
import router from '@/router'
import { clearTokens, getAccessToken, getRefreshToken, setTokens } from '@/utils/token'

const API_PREFIX = import.meta.env.VITE_API_PREFIX || '/api'
const REQUEST_TIMEOUT = 15000
/** 这些接口本身用于建立会话，不参与 401 自动续期 */
const AUTH_FREE_PATHS = ['/auth/login', '/auth/register', '/auth/refresh']

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

/**
 * 底层发送。
 *
 * 这里刻意使用 XMLHttpRequest 而非 fetch：Mock.js 通过劫持 XMLHttpRequest 实现
 * 请求拦截，fetch 不会被拦截。接口层保持此签名，后续切换 axios 只需改本文件。
 */
function send<T>(url: string, options: RequestOptions, accessToken: string | null): Promise<T> {
  const { method = 'GET', body } = options
  const fullUrl = `${API_PREFIX}${url}`

  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open(method, fullUrl)
    xhr.timeout = REQUEST_TIMEOUT

    if (body !== undefined) {
      xhr.setRequestHeader('Content-Type', 'application/json')
    }
    if (accessToken) {
      xhr.setRequestHeader('Authorization', `Bearer ${accessToken}`)
    }

    xhr.onload = () => {
      let envelope: ApiEnvelope<T> | null = null
      try {
        envelope = JSON.parse(xhr.responseText) as ApiEnvelope<T>
      } catch {
        envelope = null
      }

      if (xhr.status < 200 || xhr.status >= 300) {
        reject(
          new ApiError(
            envelope?.message || `请求失败（${xhr.status}）`,
            envelope?.code ?? xhr.status,
            envelope?.detail,
          ),
        )
        return
      }

      if (!envelope) {
        reject(new ApiError('响应解析失败', -1))
        return
      }

      if (envelope.code !== 200) {
        reject(new ApiError(envelope.message || '请求失败', envelope.code, envelope.detail))
        return
      }

      resolve(envelope.data)
    }

    xhr.onerror = () => reject(new ApiError('网络异常，请稍后重试', -1))
    xhr.ontimeout = () => reject(new ApiError('请求超时', -2))

    xhr.send(body === undefined ? null : JSON.stringify(body))
  })
}

function toApiError(error: unknown): ApiError {
  return error instanceof ApiError ? error : new ApiError('请求失败', -1)
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

      const tokens = await send<{ access_token: string; refresh_token: string }>(
        '/auth/refresh',
        { method: 'POST', body: { refresh_token: refreshToken }, auth: false },
        null,
      )
      setTokens(tokens.access_token, tokens.refresh_token)
      return tokens.access_token
    })().finally(() => {
      refreshPromise = null
    })
  }
  return refreshPromise
}

/**
 * 统一请求入口。
 *
 * 自动携带 Authorization: Bearer <access_token>；访问令牌过期（401）时用刷新
 * 令牌换新并重试一次，刷新失败则清理本地令牌并跳转登录页。
 */
export async function request<T>(url: string, options: RequestOptions = {}): Promise<T> {
  const { auth = true } = options
  const useAuth = auth && !AUTH_FREE_PATHS.some((path) => url.startsWith(path))
  const accessToken = useAuth ? getAccessToken() : null

  try {
    return await send<T>(url, options, accessToken)
  } catch (error) {
    const apiError = toApiError(error)

    if (useAuth && apiError.code === 401) {
      if (!getRefreshToken()) {
        handleAuthExpired('登录状态已失效，请重新登录')
        throw apiError
      }

      let newAccessToken: string
      try {
        newAccessToken = await refreshAccessToken()
      } catch (refreshError) {
        const refreshApiError = toApiError(refreshError)
        handleAuthExpired(
          refreshApiError.code === 401 ? '登录状态已过期，请重新登录' : refreshApiError.message,
        )
        throw refreshApiError
      }

      try {
        return await send<T>(url, options, newAccessToken)
      } catch (retryError) {
        const retryApiError = toApiError(retryError)
        if (retryApiError.code === 401) {
          handleAuthExpired('登录状态已过期，请重新登录')
        } else if (!options.silent) {
          notifyError(retryApiError.message)
        }
        throw retryApiError
      }
    }

    if (!options.silent) {
      notifyError(apiError.message)
    }
    throw apiError
  }
}
