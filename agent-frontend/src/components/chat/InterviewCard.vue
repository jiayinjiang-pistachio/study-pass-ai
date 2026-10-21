<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ArrowRight, Tickets } from '@element-plus/icons-vue'
import { fetchInterview } from '@/api/interview'
import type { InterviewDetail, InterviewQa } from '@/api/interview'

const props = defineProps<{ interviewId: number }>()

const visible = ref(false)
const loading = ref(false)
const loaded = ref(false)
const failed = ref(false)
const detail = ref<InterviewDetail | null>(null)

const qaList = computed<InterviewQa[]>(() => {
  const list = detail.value?.qa_object
  return Array.isArray(list) ? list : []
})

function toText(value: string | undefined): string {
  return typeof value === 'string' ? value : ''
}

async function load(): Promise<void> {
  if (loading.value) return
  loading.value = true
  failed.value = false
  try {
    detail.value = await fetchInterview(props.interviewId)
    loaded.value = true
  } catch {
    failed.value = true
  } finally {
    loading.value = false
  }
}

function open(): void {
  visible.value = true
  if (!loaded.value) void load()
}

watch(
  () => props.interviewId,
  () => {
    loaded.value = false
    failed.value = false
    detail.value = null
  },
)
</script>

<template>
  <button type="button" class="interview-card" @click="open">
    <span class="interview-card__icon">
      <el-icon><Tickets /></el-icon>
    </span>
    <span class="interview-card__body">
      <span class="interview-card__title">面试记录</span>
      <span class="interview-card__desc">点击查看本次模拟面试的问答详情</span>
    </span>
    <el-icon class="interview-card__arrow"><ArrowRight /></el-icon>
  </button>

  <el-dialog v-model="visible" title="面试问答详情" width="min(680px, 92vw)" append-to-body>
    <div v-loading="loading" class="interview-detail">
      <template v-if="qaList.length">
        <div
          v-for="(qa, index) in qaList"
          :key="qa.id ?? index"
          class="interview-detail__item"
        >
          <p class="interview-detail__question">
            {{ index + 1 }}. {{ toText(qa.question) || '（无问题）' }}
          </p>
          <p class="interview-detail__answer">
            {{ toText(qa.answer) || '（暂无回答）' }}
          </p>
        </div>
      </template>

      <div v-else-if="failed" class="interview-detail__state">
        <span>面试记录加载失败</span>
        <el-button link type="primary" @click="load">重试</el-button>
      </div>

      <el-empty
        v-else-if="!loading"
        description="暂无问答记录"
        :image-size="80"
      />
    </div>
  </el-dialog>
</template>

<style lang="scss" scoped>
.interview-card {
  display: flex;
  align-items: center;
  gap: 12px;
  max-width: min(660px, 100%);
  padding: 14px 16px;
  border: 1px solid var(--color-border);
  border-radius: 12px;
  background: var(--color-surface);
  text-align: left;
  cursor: pointer;
  transition: border-color 0.2s;

  &:hover {
    border-color: var(--color-brand);

    .interview-card__arrow {
      color: var(--color-brand);
      transform: translateX(2px);
    }
  }

  &__icon {
    flex: none;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 38px;
    height: 38px;
    border-radius: 10px;
    background: var(--color-brand-soft);
    color: var(--color-brand);
    font-size: 20px;
  }

  &__body {
    display: flex;
    flex: 1;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
  }

  &__title {
    font-size: 14px;
    font-weight: 600;
    color: var(--color-text);
  }

  &__desc {
    font-size: 12px;
    color: var(--color-text-muted);
  }

  &__arrow {
    flex: none;
    color: var(--color-text-muted);
    transition:
      color 0.2s,
      transform 0.2s;
  }
}

.interview-detail {
  min-height: 120px;
  max-height: 60vh;
  overflow-y: auto;

  &__item {
    padding: 12px 0;
    border-bottom: 1px solid var(--color-divider);

    &:first-child {
      padding-top: 0;
    }

    &:last-child {
      border-bottom: none;
    }
  }

  &__question {
    margin: 0 0 6px;
    font-size: 14px;
    font-weight: 600;
    line-height: 1.6;
    color: var(--color-text);
  }

  &__answer {
    margin: 0;
    font-size: 14px;
    line-height: 1.7;
    white-space: pre-wrap;
    word-break: break-word;
    color: var(--color-text-secondary);
  }

  &__state {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    min-height: 120px;
    font-size: 14px;
    color: var(--color-text-muted);
  }
}
</style>
