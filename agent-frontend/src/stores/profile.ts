import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import * as profileApi from '@/api/profile'
import type { ProfilePayload, UserProfile } from '@/api/profile'

/** 必填项齐全才不再展示开场白表单；0 年经验是有效值 */
function isComplete(profile: UserProfile | null): boolean {
  if (!profile) return false
  return Boolean(
    profile.targetJob?.trim() &&
      profile.yearsExperience !== null &&
      profile.targetLevel?.trim(),
  )
}

export const useProfileStore = defineStore('profile', () => {
  const profile = ref<UserProfile | null>(null)
  const loaded = ref(false)
  const loading = ref(false)

  /** 资料未填时展示新会话开场白；读取失败（loaded=false）不误弹表单 */
  const needsOnboarding = computed(
    () => loaded.value && !isComplete(profile.value),
  )

  /** 读取当前用户画像；失败只保持未加载状态，不阻断聊天 */
  async function refresh(): Promise<void> {
    if (loading.value) return
    loading.value = true
    try {
      profile.value = await profileApi.fetchMyProfile()
      loaded.value = true
    } catch {
      loaded.value = false
    } finally {
      loading.value = false
    }
  }

  /** 已存在则更新，否则创建；成功后同步本地画像，开场白随之消失 */
  async function save(payload: ProfilePayload): Promise<void> {
    const saved = profile.value
      ? await profileApi.updateProfile(payload)
      : await profileApi.createProfile(payload)
    profile.value = saved
    loaded.value = true
  }

  function reset(): void {
    profile.value = null
    loaded.value = false
    loading.value = false
  }

  return { profile, loaded, loading, needsOnboarding, refresh, save, reset }
})
