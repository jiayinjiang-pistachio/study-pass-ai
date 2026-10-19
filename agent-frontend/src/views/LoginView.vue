<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Lock, User } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { ModuleKey } from '@/types/conversation'

const AuthTab = {
  Login: 'login',
  Register: 'register',
} as const
type AuthTab = (typeof AuthTab)[keyof typeof AuthTab]

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const activeTab = ref<AuthTab>(AuthTab.Login)
const loading = ref(false)
const form = reactive({
  username: '',
  password: '',
  confirmPassword: '',
})

const isRegister = computed(() => activeTab.value === AuthTab.Register)
const submitLabel = computed(() => (isRegister.value ? '注册' : '登录'))

function switchTab(tab: AuthTab): void {
  if (loading.value || activeTab.value === tab) return
  activeTab.value = tab
  form.password = ''
  form.confirmPassword = ''
}

function validate(): string | null {
  const username = form.username.trim()
  if (!username) return '请输入用户名'
  if (username.length > 32) return '用户名长度不能超过 32 位'
  if (!form.password) return '请输入密码'

  if (!isRegister.value) return null

  if (form.password.length < 6) return '密码长度至少 6 位'
  if (form.password.length > 72) return '密码长度不能超过 72 位'
  if (!/[A-Za-z]/.test(form.password) || !/\d/.test(form.password)) {
    return '密码需同时包含字母和数字'
  }
  if (form.password.toLowerCase().includes(username.toLowerCase())) {
    return '密码不能包含用户名'
  }
  if (!form.confirmPassword) return '请再次输入密码'
  if (form.password !== form.confirmPassword) return '两次输入的密码不一致'
  return null
}

/** 只接受站内路径，避免 redirect 参数被用于外站跳转 */
function resolveRedirect(): string | null {
  const value = route.query.redirect
  if (typeof value !== 'string') return null
  return value.startsWith('/') && !value.startsWith('//') ? value : null
}

async function handleSubmit(): Promise<void> {
  const error = validate()
  if (error) {
    ElMessage.warning(error)
    return
  }

  loading.value = true
  try {
    const username = form.username.trim()
    if (isRegister.value) {
      await authStore.register(username, form.password)
      ElMessage.success('注册成功，正在登录…')
      await authStore.login(username, form.password)
    } else {
      await authStore.login(username, form.password)
    }
    await router.replace(resolveRedirect() ?? { name: ModuleKey.Interview })
  } catch {
    // 错误已由请求层统一提示，这里只负责恢复表单状态
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="auth-page">
    <section class="auth-card">
      <header class="auth-card__head">
        <span class="auth-card__logo" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="24" height="24" fill="#fff">
            <path d="M12 3 1 9l11 6 9-4.91V17h2V9L12 3z" />
            <path d="M5 13.18v3.82C5 17.79 8.13 19.5 12 19.5s7-1.71 7-2.5v-3.82l-7 3.82-7-3.82z" />
          </svg>
        </span>
        <h1 class="auth-card__title">学面通AI</h1>
      </header>

      <div class="auth-card__avatar" aria-hidden="true">
        <svg viewBox="0 0 120 120">
          <defs>
            <linearGradient id="auth-sky" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stop-color="#8ecdf5" />
              <stop offset="62%" stop-color="#e3f4fc" />
              <stop offset="100%" stop-color="#fbe7c2" />
            </linearGradient>
            <linearGradient id="auth-sea" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stop-color="#7ccfe0" />
              <stop offset="100%" stop-color="#43a9c6" />
            </linearGradient>
          </defs>
          <circle cx="60" cy="60" r="60" fill="url(#auth-sky)" />
          <circle cx="84" cy="33" r="11" fill="#ffd86b" />
          <path d="M0 72 Q30 64 60 72 T120 72 V120 H0 Z" fill="url(#auth-sea)" opacity="0.92" />
          <path d="M0 84 Q30 76 60 84 T120 84 V120 H0 Z" fill="#2f93b4" opacity="0.5" />
          <path d="M0 96 Q30 90 60 96 T120 96 V120 H0 Z" fill="#f5dfb3" />
          <path d="M0 104 Q30 98 60 104 T120 104 V120 H0 Z" fill="#efd09b" />
        </svg>
      </div>

      <div class="auth-tabs" role="tablist">
        <button
          type="button"
          role="tab"
          class="auth-tabs__item"
          :class="{ 'is-active': activeTab === AuthTab.Login }"
          :aria-selected="activeTab === AuthTab.Login"
          @click="switchTab(AuthTab.Login)"
        >
          登录
        </button>
        <button
          type="button"
          role="tab"
          class="auth-tabs__item"
          :class="{ 'is-active': activeTab === AuthTab.Register }"
          :aria-selected="activeTab === AuthTab.Register"
          @click="switchTab(AuthTab.Register)"
        >
          注册
        </button>
      </div>

      <form class="auth-form" @submit.prevent="handleSubmit">
        <el-input
          v-model="form.username"
          size="large"
          placeholder="用户名或邮箱"
          :prefix-icon="User"
          autocomplete="username"
        />
        <el-input
          v-model="form.password"
          type="password"
          size="large"
          show-password
          placeholder="密码"
          :prefix-icon="Lock"
          :autocomplete="isRegister ? 'new-password' : 'current-password'"
        />
        <el-input
          v-if="isRegister"
          v-model="form.confirmPassword"
          type="password"
          size="large"
          show-password
          placeholder="确认密码"
          :prefix-icon="Lock"
          autocomplete="new-password"
        />
        <el-button
          class="auth-form__submit"
          type="primary"
          size="large"
          native-type="submit"
          :loading="loading"
        >
          {{ submitLabel }}
        </el-button>
      </form>
    </section>
  </div>
</template>

<style lang="scss" scoped>
.auth-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100%;
  padding: 40px 20px;
  background:
    radial-gradient(circle at 16% 10%, rgba(255, 196, 120, 0.2), transparent 42%),
    radial-gradient(circle at 84% 90%, rgba(255, 215, 130, 0.16), transparent 40%),
    var(--color-bg-page);
}

.auth-card {
  width: 100%;
  max-width: 460px;
  padding: 36px 42px 42px;
  border-radius: 24px;
  background: var(--color-surface);
  box-shadow: 0 24px 60px rgba(63, 45, 20, 0.1);

  &__head {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 12px;
  }

  &__logo {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 46px;
    height: 46px;
    border-radius: 14px;
    background: linear-gradient(135deg, var(--color-accent-hover), var(--color-accent));
    box-shadow: 0 8px 18px rgba(255, 122, 26, 0.28);
  }

  &__title {
    font-size: 24px;
    font-weight: 700;
    letter-spacing: 0.5px;
    color: var(--color-text);
  }

  &__avatar {
    width: 76px;
    height: 76px;
    margin: 24px auto 18px;
    border-radius: 50%;
    overflow: hidden;
    box-shadow:
      0 0 0 4px var(--color-surface),
      0 0 0 5px var(--color-border);

    svg {
      display: block;
      width: 100%;
      height: 100%;
    }
  }
}

.auth-tabs {
  display: flex;
  justify-content: center;
  gap: 40px;
  margin-bottom: 24px;
  border-bottom: 1px solid var(--color-divider);

  &__item {
    position: relative;
    padding: 10px 2px 12px;
    border: none;
    background: none;
    color: var(--color-text-muted);
    font-size: 17px;
    line-height: 1.2;
    cursor: pointer;
    transition: color 0.2s;

    &:hover {
      color: var(--color-text-secondary);
    }

    &.is-active {
      color: var(--color-text);
      font-weight: 600;
    }

    &.is-active::after {
      content: '';
      position: absolute;
      left: 50%;
      bottom: -1px;
      width: 28px;
      height: 3px;
      border-radius: 2px;
      background: var(--color-accent);
      transform: translateX(-50%);
    }
  }
}

.auth-form {
  display: flex;
  flex-direction: column;
  gap: 16px;

  :deep(.el-input__wrapper) {
    height: 46px;
    padding: 0 14px;
    border-radius: 10px;
    background: #fbfaf8;
    box-shadow: 0 0 0 1px var(--color-border) inset;
    transition: box-shadow 0.2s;
  }

  :deep(.el-input__wrapper:hover) {
    box-shadow: 0 0 0 1px #dedbd5 inset;
  }

  :deep(.el-input__wrapper.is-focus) {
    box-shadow: 0 0 0 1px var(--color-accent) inset;
  }

  :deep(.el-input__prefix-inner) {
    color: var(--color-text-muted);
  }

  :deep(.el-input__inner) {
    font-size: 15px;
    color: var(--color-text);
  }

  :deep(.el-input__inner::placeholder) {
    color: var(--color-text-muted);
  }

  &__submit {
    --el-button-bg-color: var(--color-accent);
    --el-button-border-color: var(--color-accent);
    --el-button-hover-bg-color: var(--color-accent-hover);
    --el-button-hover-border-color: var(--color-accent-hover);
    --el-button-active-bg-color: var(--color-accent-active);
    --el-button-active-border-color: var(--color-accent-active);
    height: 48px;
    margin-top: 6px;
    border-radius: 10px;
    font-size: 16px;
    font-weight: 600;
    letter-spacing: 2px;
  }
}

@media (max-width: 520px) {
  .auth-page {
    padding: 24px 16px;
  }

  .auth-card {
    padding: 28px 22px 32px;
    border-radius: 20px;
  }
}
</style>
