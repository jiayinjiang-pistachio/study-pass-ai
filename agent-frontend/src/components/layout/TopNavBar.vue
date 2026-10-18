<script setup lang="ts">
import ModuleTabs from './ModuleTabs.vue'
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

  @media (max-width: 768px) {
    gap: 20px;
    padding: 0 16px;
  }
}
</style>
