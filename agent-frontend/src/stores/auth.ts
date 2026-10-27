import { ref } from 'vue'
import { defineStore } from 'pinia'
import * as authApi from '@/api/auth'
import type { AuthUser } from '@/api/auth'
import * as fileApi from '@/api/file'
import { clearTokens, getAccessToken, setTokens } from '@/utils/token'
import { useChatStore } from './chat'
import { useConversationStore } from './conversation'
import { useNoteStore } from './note'
import { useProfileStore } from './profile'

/**
 * 清空所有按用户隔离的页面状态（会话列表、消息缓存、笔记、画像）。
 * 这些 store 跨路由存活，不清理会导致切换账号后仍展示上一个账号的数据。
 */
function resetUserScopedStores(): void {
  useConversationStore().reset()
  useChatStore().reset()
  useNoteStore().reset()
  useProfileStore().reset()
}

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
    // 令牌过期后重新登录、或直接切换账号时也要清掉上一个账号的页面状态
    resetUserScopedStores()
    await loadUser()
    // 若加载用户时令牌已被请求层判定失效，这里同步回真实状态
    loggedIn.value = Boolean(getAccessToken())
  }

  async function register(username: string, password: string): Promise<void> {
    await authApi.register({ username, password })
  }

  /** 登录后上传头像：走后端通用文件接口，uploadPurpose=1 时同步更新 avatar 字段 */
  async function uploadAvatar(file: File): Promise<void> {
    const uploaded = await fileApi.uploadFile(file, { uploadPurpose: 1 })
    if (uploaded.kind !== fileApi.FileKind.Image) return
    // 后端返回的 url 是 MinIO 内部路径，浏览器不可直接加载；
    // 重新拉取用户信息，拿到后端转换后的头像访问地址
    await loadUser()
  }

  function logout(): void {
    clearTokens()
    user.value = null
    loggedIn.value = false
    resetUserScopedStores()
  }

  return { user, loggedIn, loadUser, login, register, uploadAvatar, logout }
})
