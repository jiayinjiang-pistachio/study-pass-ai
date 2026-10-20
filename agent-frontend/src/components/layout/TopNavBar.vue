<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { SwitchButton } from '@element-plus/icons-vue'
import ModuleTabs from './ModuleTabs.vue'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()

onMounted(() => {
  void authStore.loadUser()
})

async function handleLogout(): Promise<void> {
  authStore.logout()
  await router.replace({ name: 'login' })
}
</script>

<template>
  <header class="top-nav">
    <div class="top-nav__brand">
      <span class="top-nav__logo" aria-hidden="true">
        <svg viewBox="0 0 24 24" width="20" height="20" fill="#fff">
          <path d="M12 3 1 9l11 6 9-4.91V17h2V9L12 3z" />
          <path d="M5 13.18v3.82C5 17.79 8.13 19.5 12 19.5s7-1.71 7-2.5v-3.82l-7 3.82-7-3.82z" />
        </svg>
      </span>
      <span class="top-nav__title">学面通AI</span>
    </div>

    <ModuleTabs />

    <div class="top-nav__user">
      <div v-if="authStore.user" class="top-nav__profile">
        <el-avatar
          :size="30"
          :src="authStore.user.avatar ?? undefined"
          class="top-nav__avatar"
        >
          {{ authStore.user.username.slice(0, 1).toUpperCase() }}
        </el-avatar>
        <span class="top-nav__username text-ellipsis">{{ authStore.user.username }}</span>
      </div>
      <el-button class="top-nav__logout" text :icon="SwitchButton" @click="handleLogout">
        退出登录
      </el-button>
    </div>
  </header>
</template>

<style lang="scss" scoped>
.top-nav {
  flex: none;
  display: flex;
  align-items: center;
  gap: 48px;
  height: var(--navbar-height);
  padding: 0 24px;
  background: var(--color-surface);
  border-bottom: 1px solid var(--color-divider);

  &__brand {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  &__logo {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 40px;
    height: 40px;
    border-radius: 50%;
    background: linear-gradient(135deg, var(--color-brand-light), var(--color-brand));
    box-shadow: 0 2px 6px rgba(245, 197, 24, 0.35);
  }

  &__title {
    font-size: 18px;
    font-weight: 700;
    letter-spacing: 0.5px;
    color: var(--color-text);
  }

  &__user {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-left: auto;
  }

  &__profile {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  &__avatar {
    flex: none;
    background: var(--color-accent-soft);
    color: var(--color-accent);
    font-size: 13px;
    font-weight: 600;
  }

  &__username {
    max-width: 140px;
    font-size: 14px;
    color: var(--color-text-secondary);
  }

  &__logout {
    --el-button-text-color: var(--color-text-secondary);
    --el-button-hover-text-color: var(--color-accent);
    --el-button-hover-bg-color: var(--color-accent-soft);
    --el-button-hover-link-text-color: var(--color-accent);
    --el-button-active-color: var(--color-accent);
  }

  @media (max-width: 768px) {
    gap: 20px;
    padding: 0 16px;

    &__username {
      display: none;
    }
  }
}
</style>
