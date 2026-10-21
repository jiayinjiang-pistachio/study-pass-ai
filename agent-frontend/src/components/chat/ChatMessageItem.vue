<script setup lang="ts">
import { computed } from 'vue'
import { Service, User } from '@element-plus/icons-vue'
import InterviewCard from './InterviewCard.vue'
import MsgFile from './MsgFile.vue'
import type { ChatMessage } from '@/types/chat'

const props = defineProps<{ message: ChatMessage }>()

const hasRequest = computed(
  () =>
    props.message.requestText.trim().length > 0 ||
    props.message.requestSegments.length > 0,
)

const showInterviewCard = computed(
  () => props.message.status === 1 && props.message.interviewId !== null,
)

/** 生成中 / 失败的状态提示，正文为空时展示 */
const responsePlaceholder = computed(() => {
  if (props.message.responseText.trim().length > 0) return ''
  if (props.message.status === 0) return '正在生成…'
  if (props.message.status === 2) return '生成失败'
  return ''
})

const hasResponse = computed(
  () =>
    props.message.responseText.trim().length > 0 ||
    props.message.responseSegments.length > 0 ||
    showInterviewCard.value ||
    responsePlaceholder.value.length > 0,
)

const timeLabel = computed(() => {
  const diff = Date.now() - props.message.createdAt
  if (diff < 60 * 1000) return '刚刚'
  if (diff < 60 * 60 * 1000) return `${Math.floor(diff / (60 * 1000))}分钟前`

  const date = new Date(props.message.createdAt)
  const hh = String(date.getHours()).padStart(2, '0')
  const mm = String(date.getMinutes()).padStart(2, '0')
  const today = new Date()
  if (date.toDateString() === today.toDateString()) return `${hh}:${mm}`
  return `${date.getMonth() + 1}月${date.getDate()}日 ${hh}:${mm}`
})
</script>

<template>
  <div class="msg-pair">
    <div v-if="hasRequest" class="msg msg--user">
      <span class="msg__avatar">
        <el-icon><User /></el-icon>
      </span>

      <div class="msg__body">
        <div v-if="message.requestText.trim().length" class="msg__bubble">
          {{ message.requestText }}
        </div>
        <div v-if="message.requestSegments.length" class="msg__files">
          <MsgFile
            v-for="(segment, index) in message.requestSegments"
            :key="`req-${segment.resourceId}-${index}`"
            :segment="segment"
          />
        </div>
      </div>
    </div>

    <div v-if="hasResponse" class="msg msg--ai">
      <span class="msg__avatar">
        <el-icon><Service /></el-icon>
      </span>

      <div class="msg__body">
        <div
          v-if="message.responseText.trim().length || responsePlaceholder"
          class="msg__bubble"
          :class="{ 'msg__bubble--muted': !message.responseText.trim().length }"
        >
          {{ message.responseText.trim().length ? message.responseText : responsePlaceholder }}
        </div>
        <div v-if="message.responseSegments.length" class="msg__files">
          <MsgFile
            v-for="(segment, index) in message.responseSegments"
            :key="`res-${segment.resourceId}-${index}`"
            :segment="segment"
          />
        </div>
        <InterviewCard
          v-if="showInterviewCard && message.interviewId !== null"
          :interview-id="message.interviewId"
        />
      </div>
    </div>

    <span class="msg-pair__time">{{ timeLabel }}</span>
  </div>
</template>

<style lang="scss" scoped>
.msg-pair {
  display: flex;
  flex-direction: column;
  gap: 14px;

  &__time {
    padding-left: 50px;
    font-size: 12px;
    color: var(--color-text-muted);
  }
}

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
    gap: 8px;
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

    &--muted {
      color: var(--color-text-muted);
    }
  }

  &__files {
    display: flex;
    flex-direction: column;
    gap: 8px;
    max-width: min(660px, 100%);
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
