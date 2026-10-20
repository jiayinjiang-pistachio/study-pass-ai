import { ref } from 'vue'
import { defineStore } from 'pinia'
import * as authApi from '@/api/auth'
import type { AuthUser } from '@/api/auth'
import * as fileApi from '@/api/file'
import { clearTokens, getAccessToken, setTokens } from '@/utils/token'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<AuthUser | null>(null)
  /** 令牌存于 localStorage，此标记只用于界面展示，鉴权仍以请求层为准 */
  const loggedIn = ref(Boolean(getAccessToken()))

  async function loadUser(): Promise<void> {
    if (!getAccessToken()) return
    try {
      user.value = await authApi.fetchCurrentUser(true)
    } catch {
      user.value = null
    }
  }

  async function login(username: string, password: string): Promise<void> {
    const tokens = await authApi.login({ username, password })
    setTokens(tokens.access_token, tokens.refresh_token)
    loggedIn.value = true
    await loadUser()
    // 若加载用户时令牌已被请求层判定失效，这里同步回真实状态
    loggedIn.value = Boolean(getAccessToken())
  }

  async function register(username: string, password: string): Promise<void> {
    await authApi.register({ username, password })
  }

  /** 登录后上传头像：走后端通用文件接口，图片会同步更新 avatar 字段 */
  async function uploadAvatar(file: File): Promise<void> {
    const uploaded = await fileApi.uploadFile(file)
    if (uploaded.kind !== fileApi.FileKind.Image) return
    if (user.value) {
      user.value = { ...user.value, avatar: uploaded.url }
    } else {
      await loadUser()
    }
  }

  function logout(): void {
    clearTokens()
    user.value = null
    loggedIn.value = false
  }

  return { user, loggedIn, loadUser, login, register, uploadAvatar, logout }
})
