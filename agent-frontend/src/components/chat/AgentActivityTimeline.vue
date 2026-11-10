<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  ArrowRight,
  CircleCheckFilled,
  CircleCloseFilled,
  Loading,
} from '@element-plus/icons-vue'
import {
  AgentActivityStatus,
  type AgentActivityNode,
} from '@/types/chat'

const props = withDefaults(
  defineProps<{ nodes: AgentActivityNode[]; active?: boolean }>(),
  { active: false },
)

/** 完成后默认保持展开，仅由用户手动收起 */
const manualOpen = ref(true)
const hasFailed = computed(() =>
  props.nodes.some((node) => node.status === AgentActivityStatus.Failed),
)
const doneCount = computed(
  () =>
    props.nodes.filter((node) => node.status === AgentActivityStatus.Done)
      .length,
)
const expanded = computed(
  () => Boolean(props.active) || hasFailed.value || manualOpen.value,
)

// 新一轮开始执行时恢复展开，避免上次手动收起的状态残留
watch(
  () => props.active,
  (active) => {
    if (active) manualOpen.value = true
  },
)

function toggle(): void {
  // 执行中或失败时保持展开，确保错误信息始终可见
  if (props.active || hasFailed.value) return
  manualOpen.value = !manualOpen.value
}
</script>

<template>
  <div class="timeline" :class="{ 'is-expanded': expanded }">
    <button
      v-if="!active && !hasFailed"
      type="button"
      class="timeline__summary"
      :aria-expanded="expanded"
      @click="toggle"
    >
      <span class="timeline__badge is-done">
        <el-icon><CircleCheckFilled /></el-icon>
      </span>
      <span class="timeline__summary-text">已完成 {{ doneCount }} 个步骤</span>
      <span class="timeline__toggle-text">{{ expanded ? '收起' : '详情' }}</span>
      <el-icon class="timeline__chevron" :class="{ 'is-open': expanded }">
        <ArrowRight />
      </el-icon>
    </button>
    <div v-else class="timeline__header">
      <span class="timeline__badge" :class="active ? 'is-running' : 'is-failed'">
        <el-icon v-if="active" class="timeline__spin"><Loading /></el-icon>
        <el-icon v-else><CircleCloseFilled /></el-icon>
      </span>
      <span class="timeline__header-text">{{ active ? '正在执行' : '执行失败' }}</span>
      <span v-if="!active && doneCount" class="timeline__count">
        {{ doneCount }} 步完成
      </span>
    </div>

    <ol v-if="expanded" class="timeline__list">
      <li
        v-for="(node, index) in nodes"
        :key="`${node.agent}:${node.node}:${index}`"
        class="timeline__item"
        :class="`is-${node.status}`"
      >
        <span class="timeline__dot">
          <el-icon v-if="node.status === AgentActivityStatus.Done">
            <CircleCheckFilled />
          </el-icon>
          <el-icon v-else-if="node.status === AgentActivityStatus.Failed">
            <CircleCloseFilled />
          </el-icon>
          <el-icon v-else class="timeline__spin"><Loading /></el-icon>
        </span>
        <div class="timeline__text">
          <div class="timeline__title">{{ node.title }}</div>
          <div v-if="node.detail" class="timeline__detail">
            {{ node.detail }}
          </div>
          <div
            v-if="node.status === AgentActivityStatus.Failed && node.error"
            class="timeline__error"
          >
            {{ node.error }}
          </div>
        </div>
      </li>
    </ol>
  </div>
</template>

<style lang="scss" scoped>
.timeline {
  // 自适应宽度，避免被消息行的剩余空间压缩导致文字折行
  align-self: flex-start;
  width: fit-content;
  max-width: min(660px, 100%);
  font-size: 13px;
  line-height: 1.6;

  // 收起时只保留一个轻量胶囊，展开后才呈现为卡片
  &.is-expanded {
    padding: 12px 14px;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-bubble);
    background: var(--color-surface);

    // 展开后摘要退化为卡片标题，与节点列表用分隔线隔开
    .timeline__summary,
    .timeline__header {
      padding: 0 0 10px;
      border: none;
      border-bottom: 1px solid var(--color-divider);
      border-radius: 0;
      background: transparent;
    }

    .timeline__summary:hover {
      background: transparent;
      color: var(--color-text);
    }
  }

  &__summary,
  &__header {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    color: var(--color-text-secondary);
  }

  &__summary {
    padding: 7px 12px 7px 10px;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-pill);
    background: var(--color-surface);
    font-family: inherit;
    font-size: 13px;
    line-height: 1.4;
    text-align: left;
    cursor: pointer;
    transition:
      background-color 0.2s,
      border-color 0.2s,
      color 0.2s;

    &:hover {
      border-color: var(--color-divider);
      background: var(--color-hover);
      color: var(--color-text);
    }

    &:focus-visible {
      outline: 2px solid var(--color-accent);
      outline-offset: 2px;
    }
  }

  &__badge {
    flex: none;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 20px;
    height: 20px;
    border-radius: 50%;
    font-size: 15px;

    &.is-done {
      color: var(--color-success);
      background: var(--color-success-soft);
    }

    &.is-running {
      color: var(--color-accent);
      background: var(--color-accent-soft);
    }

    &.is-failed {
      color: var(--color-danger);
      background: var(--color-danger-soft);
    }
  }

  &__summary-text {
    flex: none;
    white-space: nowrap;
    color: var(--color-text);
    font-weight: 500;
  }

  &__toggle-text {
    flex: none;
    margin-left: auto;
    white-space: nowrap;
    font-size: 12px;
    color: var(--color-text-muted);
  }

  &__chevron {
    flex: none;
    font-size: 12px;
    color: var(--color-text-muted);
    transition: transform 0.2s;

    &.is-open {
      transform: rotate(90deg);
    }
  }

  &__header-text {
    flex: none;
    white-space: nowrap;
    color: var(--color-text);
    font-weight: 500;
  }

  &__count {
    flex: none;
    padding: 1px 8px;
    border-radius: var(--radius-pill);
    background: var(--color-hover);
    color: var(--color-text-muted);
    font-size: 12px;
    white-space: nowrap;
  }

  &__list {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 12px;
    margin: 12px 0 0;
    padding: 0;
    list-style: none;
    animation: timeline-fade-in 0.18s ease-out;

    // 节点间的竖向轨道，由各节点圆点遮住端点
    &::before {
      content: '';
      position: absolute;
      top: 9px;
      bottom: 9px;
      left: 9px;
      width: 2px;
      border-radius: 1px;
      background: var(--color-divider);
    }
  }

  &__item {
    position: relative;
    display: flex;
    gap: 10px;
    padding-left: 26px;
  }

  &__dot {
    position: absolute;
    top: 3px;
    left: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 20px;
    height: 20px;
    border-radius: 50%;
    background: var(--color-surface);
    font-size: 16px;

    .is-done & {
      color: var(--color-success);
    }

    .is-failed & {
      color: var(--color-danger);
    }

    .is-running & {
      color: var(--color-accent);
    }
  }

  &__text {
    min-width: 0;
    padding-top: 1px;
  }

  &__title {
    color: var(--color-text);
    font-weight: 500;
  }

  &__detail {
    margin-top: 1px;
    font-size: 12px;
    color: var(--color-text-muted);
    word-break: break-word;
  }

  &__error {
    margin-top: 6px;
    padding: 6px 9px;
    border-radius: var(--radius-control);
    background: var(--color-danger-soft);
    color: var(--color-danger);
    font-size: 12px;
    line-height: 1.5;
    word-break: break-word;
  }

  &__spin {
    animation: timeline-spin 1s linear infinite;
  }
}

@keyframes timeline-spin {
  to {
    transform: rotate(360deg);
  }
}

@keyframes timeline-fade-in {
  from {
    opacity: 0;
    transform: translateY(-2px);
  }

  to {
    opacity: 1;
    transform: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .timeline__spin {
    animation: none;
  }

  .timeline__chevron,
  .timeline__summary {
    transition: none;
  }

  .timeline__list {
    animation: none;
  }
}
</style>
