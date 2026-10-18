<script setup lang="ts">
import { computed } from 'vue'
import { Service, User } from '@element-plus/icons-vue'
import type { ChatMessage } from '@/types/chat'

const props = defineProps<{ message: ChatMessage }>()

const isAi = computed(() => props.message.role === 'ai')

const timeLabel = computed(() => {
  const diff = Date.now() - props.message.createdAt
  if (diff < 60 * 1000) return '刚刚'
  if (diff < 60 * 60 * 1000) return `${Math.floor(diff / (60 * 1000))}分钟前`
  const date = new Date(props.message.createdAt)
  const hh = String(date.getHours()).padStart(2, '0')
  const mm = String(date.getMinutes()).padStart(2, '0')
  return `${hh}:${mm}`
})
</script>

<template>
  <div class="msg" :class="isAi ? 'msg--ai' : 'msg--user'">
    <span class="msg__avatar">
      <el-icon><Service v-if="isAi" /><User v-else /></el-icon>
    </span>

    <div class="msg__body">
      <div class="msg__bubble">{{ message.content }}</div>
      <span class="msg__time">{{ timeLabel }}</span>
    </div>
  </div>
</template>

<style lang="scss" scoped>
.msg {
  display: flex;
  align-items: flex-start;
  gap: 12px;

  &__avatar {
    flex: none;
    display: flex;
    align-items: center;
    justify-content: center;
    width: var(--avatar-size);
    height: var(--avatar-size);
    border-radius: 50%;
    color: #fff;
    font-size: 20px;
  }

  &__body {
    display: flex;
    flex-direction: column;
    gap: 6px;
    min-width: 0;
  }

  &__bubble {
    max-width: min(660px, 100%);
    padding: 14px 18px;
    border-radius: var(--radius-bubble);
    font-size: 15px;
    line-height: 1.7;
    white-space: pre-wrap;
    word-break: break-word;
  }

  &__time {
    padding-left: 4px;
    font-size: 12px;
    color: var(--color-text-muted);
  }

  &--ai {
    .msg__avatar {
      background: #3b82f6;
    }

    .msg__bubble {
      background: var(--color-surface);
      border: 1px solid var(--color-border);
      color: var(--color-text);
    }
  }

  &--user {
    .msg__avatar {
      background: #9aa4b2;
    }

    .msg__bubble {
      background: var(--color-bubble-user);
      color: var(--color-text);
    }
  }
}
</style>
