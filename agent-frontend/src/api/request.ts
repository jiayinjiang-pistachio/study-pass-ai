const API_PREFIX = import.meta.env.VITE_API_PREFIX || '/api'

/** 后端统一响应结构 */
export interface ApiEnvelope<T> {
  code: number
  message: string
  data: T
}

export class ApiError extends Error {
  code: number

  constructor(message: string, code: number) {
    super(message)
    this.name = 'ApiError'
    this.code = code
  }
}

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'DELETE'

export interface RequestOptions {
  method?: HttpMethod
  body?: unknown
}

/**
 * 统一请求入口。
 *
 * 这里刻意使用 XMLHttpRequest 而非 fetch：Mock.js 通过劫持 XMLHttpRequest 实现
 * 请求拦截，fetch 不会被拦截。接口层保持此签名，后续切换 axios 只需改本文件。
 */
export function request<T>(url: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body } = options
  const fullUrl = `${API_PREFIX}${url}`

  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open(method, fullUrl)
    xhr.timeout = 15000

    if (body !== undefined) {
      xhr.setRequestHeader('Content-Type', 'application/json')
    }

    xhr.onload = () => {
      if (xhr.status < 200 || xhr.status >= 300) {
        reject(new ApiError(`请求失败（${xhr.status}）`, xhr.status))
        return
      }

      try {
        const envelope = JSON.parse(xhr.responseText) as ApiEnvelope<T>
        if (envelope.code !== 200) {
          reject(new ApiError(envelope.message || '请求失败', envelope.code))
          return
        }
        resolve(envelope.data)
      } catch {
        reject(new ApiError('响应解析失败', -1))
      }
    }

    xhr.onerror = () => reject(new ApiError('网络异常，请稍后重试', -1))
    xhr.ontimeout = () => reject(new ApiError('请求超时', -2))

    xhr.send(body === undefined ? null : JSON.stringify(body))
  })
}
