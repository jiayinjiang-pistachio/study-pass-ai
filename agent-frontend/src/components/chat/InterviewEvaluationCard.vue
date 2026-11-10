<script setup lang="ts">
import { computed } from 'vue'
import type { InterviewEvaluation } from '@/types/chat'

const props = defineProps<{
  evaluation: InterviewEvaluation
}>()

const score = computed(() => Math.max(0, Math.min(100, props.evaluation.score)))
</script>

<template>
  <section class="evaluation-card">
    <header class="evaluation-card__header">
      <span class="evaluation-card__badge">面试复盘</span>
      <span class="evaluation-card__score">{{ score }}<small>/100</small></span>
    </header>

    <div v-if="evaluation.strengths.length" class="evaluation-card__section">
      <h4 class="evaluation-card__title">亮点</h4>
      <ul class="evaluation-card__list">
        <li v-for="(item, index) in evaluation.strengths" :key="`s-${index}`">
          {{ item }}
        </li>
      </ul>
    </div>

    <div v-if="evaluation.weaknesses.length" class="evaluation-card__section">
      <h4 class="evaluation-card__title">薄弱点</h4>
      <ul class="evaluation-card__list evaluation-card__list--weak">
        <li v-for="(item, index) in evaluation.weaknesses" :key="`w-${index}`">
          {{ item }}
        </li>
      </ul>
    </div>

    <div v-if="evaluation.review" class="evaluation-card__section">
      <h4 class="evaluation-card__title">改进建议</h4>
      <p class="evaluation-card__review">{{ evaluation.review }}</p>
    </div>
  </section>
</template>

<style lang="scss" scoped>
.evaluation-card {
  display: flex;
  flex-direction: column;
  gap: 14px;
  width: min(520px, 100%);
  padding: 16px 18px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-bubble);
  background: var(--color-surface);

  &__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }

  &__badge {
    padding: 2px 8px;
    border-radius: var(--radius-pill);
    background: var(--color-brand-soft);
    font-size: 12px;
    line-height: 1.6;
    color: var(--color-text);
  }

  &__score {
    font-size: 26px;
    font-weight: 700;
    line-height: 1.2;
    color: var(--color-text);

    small {
      margin-left: 2px;
      font-size: 13px;
      font-weight: 400;
      color: var(--color-text-muted);
    }
  }

  &__section {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  &__title {
    margin: 0;
    font-size: 13px;
    font-weight: 600;
    color: var(--color-text-secondary);
  }

  &__list {
    margin: 0;
    padding-left: 18px;
    font-size: 14px;
    line-height: 1.7;
    color: var(--color-text);

    li + li {
      margin-top: 2px;
    }

    &--weak {
      color: var(--color-warning);
    }
  }

  &__review {
    margin: 0;
    font-size: 14px;
    line-height: 1.7;
    color: var(--color-text);
    white-space: pre-wrap;
  }
}
</style>
