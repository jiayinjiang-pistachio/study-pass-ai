<script setup lang="ts">
import { ref } from 'vue'
import { ArrowDown, Document } from '@element-plus/icons-vue'
import type { MessageSource } from '@/types/chat'

defineProps<{ sources: MessageSource[] }>()

/** 超过该长度才提供「展开全文 / 收起」，避免短片段出现无意义按钮 */
const LONG_TEXT_LENGTH = 120

const expanded = ref<Record<number, boolean>>({})

function isLong(text: string): boolean {
  return text.length > LONG_TEXT_LENGTH
}

function toggle(index: number): void {
  expanded.value = {
    ...expanded.value,
    [index]: !expanded.value[index],
  }
}

function displayName(source: MessageSource): string {
  return source.fileName || '未知文档'
}

/** 相似度按百分比展示；缺失时不展示数值 */
function formatScore(score: number | null): string {
  if (score === null) return '—'
  return `${Math.round(score * 100)}%`
}
</script>

<template>
  <details class="source-panel">
    <summary class="source-panel__summary">
      <el-icon class="source-panel__arrow"><ArrowDown /></el-icon>
      <span>参考了 {{ sources.length }} 个知识片段</span>
    </summary>

    <ul class="source-panel__list">
      <li
        v-for="(source, index) in sources"
        :key="source.chunkId"
        class="source-panel__item"
      >
        <div class="source-panel__meta">
          <el-icon class="source-panel__file-icon"><Document /></el-icon>
          <span class="source-panel__file text-ellipsis" :title="displayName(source)">
            {{ displayName(source) }}
          </span>
          <span class="source-panel__score">
            相似度 {{ formatScore(source.score) }}
          </span>
        </div>

        <p
          class="source-panel__text"
          :class="{ 'is-clamped': isLong(source.text) && !expanded[index] }"
        >
          {{ source.text }}
        </p>

        <button
          v-if="isLong(source.text)"
          type="button"
          class="source-panel__toggle"
          @click="toggle(index)"
        >
          {{ expanded[index] ? '收起' : '展开全文' }}
        </button>
      </li>
    </ul>
  </details>
</template>

<style lang="scss" scoped>
.source-panel {
  max-width: min(660px, 100%);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  background: var(--color-hover);

  &__summary {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 10px 14px;
    color: var(--color-text-secondary);
    font-size: 13px;
    cursor: pointer;
    list-style: none;
    user-select: none;

    &::-webkit-details-marker {
      display: none;
    }

    &:hover {
      color: var(--color-text);
    }
  }

  &__arrow {
    flex: none;
    font-size: 14px;
    transition: transform 0.2s ease;
  }

  &[open] &__arrow {
    transform: rotate(180deg);
  }

  &__list {
    display: flex;
    flex-direction: column;
    gap: 10px;
    margin: 0;
    padding: 0 14px 14px;
    list-style: none;
  }

  &__item {
    padding: 10px 12px;
    border-radius: var(--radius-control);
    background: var(--color-surface);
  }

  &__meta {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 6px;
    min-width: 0;
  }

  &__file-icon {
    flex: none;
    font-size: 14px;
    color: var(--color-text-muted);
  }

  &__file {
    min-width: 0;
    font-size: 13px;
    color: var(--color-text-secondary);
  }

  &__score {
    flex: none;
    margin-left: auto;
    padding: 1px 8px;
    border-radius: var(--radius-pill);
    background: var(--color-accent-soft);
    color: var(--color-accent-active);
    font-size: 12px;
  }

  &__text {
    margin: 0;
    font-size: 13px;
    line-height: 1.6;
    color: var(--color-text-secondary);
    white-space: pre-wrap;
    word-break: break-word;

    &.is-clamped {
      display: -webkit-box;
      -webkit-box-orient: vertical;
      -webkit-line-clamp: 3;
      line-clamp: 3;
      overflow: hidden;
    }
  }

  &__toggle {
    margin-top: 6px;
    padding: 0;
    border: none;
    background: none;
    color: var(--color-accent);
    font-size: 12px;
    cursor: pointer;

    &:hover {
      color: var(--color-accent-hover);
    }
  }
}

@media (prefers-reduced-motion: reduce) {
  .source-panel__arrow {
    transition: none;
  }
}
</style>
