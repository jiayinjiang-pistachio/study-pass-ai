<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ArrowRight, EditPen } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import QuizDialog from './QuizDialog.vue'
import { ApiError } from '@/api/request'
import { useChatStore } from '@/stores/chat'
import type { QuizAnswer, QuizQuestion } from '@/types/quiz'

const props = defineProps<{
  sessionId: number
  requestId: string
  questions: QuizQuestion[]
}>()

const emit = defineEmits<{ 'quiz-submitted': [] }>()

const chatStore = useChatStore()
const visible = ref(false)
const submitting = ref(false)

/** 同一测评只自动弹一次：切换会话重新渲染时不再打扰用户 */
const autoOpened = new Set<string>()

watch(
  () => props.questions.length,
  (length) => {
    // 提交成功后载荷清空，入口消失时同步关闭弹窗
    if (length === 0) {
      visible.value = false
      return
    }
    if (autoOpened.has(props.requestId)) return
    autoOpened.add(props.requestId)
    visible.value = true
  },
  { immediate: true },
)

const description = computed(
  () => `共 ${props.questions.length} 道题，完成后提交获取评分`,
)

async function handleSubmit(answers: QuizAnswer[]): Promise<void> {
  if (submitting.value) return
  submitting.value = true
  try {
    await chatStore.submitQuiz(props.sessionId, props.requestId, answers)
    emit('quiz-submitted')
  } catch (error) {
    // 请求层已提示网络 / 业务错误；本地标识错误需自行提示
    if (!(error instanceof ApiError)) {
      ElMessage.error(
        error instanceof Error ? error.message : '提交失败，请稍后重试',
      )
    }
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <button type="button" class="quiz-entry" @click="visible = true">
    <span class="quiz-entry__icon">
      <el-icon><EditPen /></el-icon>
    </span>
    <span class="quiz-entry__body">
      <span class="quiz-entry__title">查看并填写测评题目</span>
      <span class="quiz-entry__desc">{{ description }}</span>
    </span>
    <el-icon class="quiz-entry__arrow"><ArrowRight /></el-icon>
  </button>

  <QuizDialog
    v-model="visible"
    :questions="questions"
    :submitting="submitting"
    @submit="handleSubmit"
  />
</template>

<style lang="scss" scoped>
.quiz-entry {
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

    .quiz-entry__arrow {
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
</style>
