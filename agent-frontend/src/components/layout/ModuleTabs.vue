<script setup lang="ts">
import { MODULE_LABELS, ModuleKey } from '@/types/conversation'

const tabs = [ModuleKey.Study, ModuleKey.Interview, ModuleKey.Note]
</script>

<template>
  <nav class="module-tabs">
    <RouterLink
      v-for="item in tabs"
      :key="item"
      :to="{ name: item }"
      class="module-tabs__item"
      active-class="is-active"
    >
      {{ MODULE_LABELS[item] }}
    </RouterLink>
  </nav>
</template>

<style lang="scss" scoped>
.module-tabs {
  display: flex;
  align-items: center;
  gap: 12px;

  &__item {
    display: inline-block;
    padding: 8px 20px;
    border-radius: var(--radius-control);
    background: #f4f4f4;
    color: #7a7f87;
    font-size: 15px;
    text-decoration: none;
    cursor: pointer;
    transition:
      background-color 0.2s,
      color 0.2s;

    &:hover {
      background: #ededed;
    }

    &.is-active {
      background: var(--color-brand-soft);
      color: var(--color-text);
      font-weight: 600;
    }
  }
}
</style>
