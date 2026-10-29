<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { QuizQuestionType } from '@/types/quiz'
import type { QuizAnswer, QuizQuestion } from '@/types/quiz'

const props = defineProps<{
  modelValue: boolean
  questions: QuizQuestion[]
  submitting: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  submit: [answers: QuizAnswer[]]
}>()

/** questionId -> 作答值：单选 / 简答为字符串，多选为字符串数组 */
const answers = ref<Record<number, string | string[]>>({})
const itemRefs = ref<Array<HTMLElement | null>>([])

function resetAnswers(): void {
  const next: Record<number, string | string[]> = {}
  for (const question of props.questions) {
    next[question.questionId] =
      question.type === QuizQuestionType.Checkbox ? [] : ''
  }
  answers.value = next
  itemRefs.value = []
}

// 每次打开都按当前题目重建答案模型，避免沿用上一次的残留选择
watch(
  () => props.modelValue,
  (visible) => {
    if (visible) resetAnswers()
  },
  { immediate: true },
)

function textAnswer(id: number): string {
  const value = answers.value[id]
  return typeof value === 'string' ? value : ''
}

function listAnswer(id: number): string[] {
  const value = answers.value[id]
  return Array.isArray(value) ? value : []
}

function setText(id: number, value: unknown): void {
  answers.value[id] =
    typeof value === 'string' ? value : value == null ? '' : String(value)
}

function setList(id: number, value: unknown): void {
  answers.value[id] = Array.isArray(value) ? value.map((item) => String(item)) : []
}

function setItemRef(index: number, el: unknown): void {
  itemRefs.value[index] = el instanceof HTMLElement ? el : null
}

function isAnswered(question: QuizQuestion): boolean {
  const value = answers.value[question.questionId]
  if (question.type === QuizQuestionType.Checkbox) {
    return Array.isArray(value) && value.length > 0
  }
  return typeof value === 'string' && value.trim().length > 0
}

function handleSubmit(): void {
  if (props.submitting) return

  const firstUnanswered = props.questions.findIndex(
    (question) => !isAnswered(question),
  )
  if (firstUnanswered !== -1) {
    ElMessage.warning('请完成所有题目后再提交')
    itemRefs.value[firstUnanswered]?.scrollIntoView({
      behavior: 'smooth',
      block: 'center',
    })
    return
  }

  emit(
    'submit',
    props.questions.map((question) => {
      const value = answers.value[question.questionId]
      return {
        question_id: question.questionId,
        value:
          question.type === QuizQuestionType.Checkbox
            ? Array.isArray(value) ? value : []
            : typeof value === 'string' ? value.trim() : '',
      }
    }),
  )
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="学习测评"
    width="min(680px, 92vw)"
    append-to-body
    :close-on-click-modal="false"
    :show-close="!submitting"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="quiz-dialog">
      <div
        v-for="(question, index) in questions"
        :key="question.questionId"
        :ref="(el) => setItemRef(index, el)"
        class="quiz-dialog__item"
      >
        <p class="quiz-dialog__stem">
          {{ index + 1 }}. {{ question.stem }}
        </p>

        <el-radio-group
          v-if="question.type === QuizQuestionType.Radio"
          :model-value="textAnswer(question.questionId)"
          :disabled="submitting"
          @update:model-value="setText(question.questionId, $event)"
        >
          <el-radio
            v-for="option in question.options"
            :key="option.key"
            :value="option.key"
            :disabled="submitting"
          >
            {{ option.key }}. {{ option.text }}
          </el-radio>
        </el-radio-group>

        <el-checkbox-group
          v-else-if="question.type === QuizQuestionType.Checkbox"
          :model-value="listAnswer(question.questionId)"
          :disabled="submitting"
          @update:model-value="setList(question.questionId, $event)"
        >
          <el-checkbox
            v-for="option in question.options"
            :key="option.key"
            :value="option.key"
            :disabled="submitting"
          >
            {{ option.key }}. {{ option.text }}
          </el-checkbox>
        </el-checkbox-group>

        <el-input
          v-else
          type="textarea"
          :rows="3"
          :model-value="textAnswer(question.questionId)"
          :disabled="submitting"
          placeholder="请输入你的答案"
          @update:model-value="setText(question.questionId, $event)"
        />
      </div>
    </div>

    <template #footer>
      <el-button :disabled="submitting" @click="emit('update:modelValue', false)">
        取消
      </el-button>
      <el-button type="primary" :loading="submitting" @click="handleSubmit">
        {{ submitting ? '正在提交答案并生成评分...' : '提交答案' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style lang="scss" scoped>
.quiz-dialog {
  max-height: 60vh;
  overflow-y: auto;

  &__item {
    padding: 14px 0;
    border-bottom: 1px solid var(--color-divider);

    &:first-child {
      padding-top: 0;
    }

    &:last-child {
      border-bottom: none;
    }
  }

  &__stem {
    margin: 0 0 10px;
    font-size: 14px;
    font-weight: 600;
    line-height: 1.7;
    color: var(--color-text);
    word-break: break-word;
  }

  :deep(.el-radio-group),
  :deep(.el-checkbox-group) {
    display: flex;
    flex-direction: column;
    align-items: stretch;
    gap: 8px;
  }

  :deep(.el-radio),
  :deep(.el-checkbox) {
    display: flex;
    align-items: flex-start;
    width: 100%;
    height: auto;
    margin-right: 0;
    padding: 8px 12px;
    border-radius: var(--radius-control);
    box-sizing: border-box;
    line-height: 1.7;
    white-space: normal;
    transition: background-color 0.2s;

    // Element Plus 默认居中，多行题干时让圆形 / 方框与首行文字对齐
    .el-radio__input,
    .el-checkbox__input {
      margin-top: 5px;
    }

    &:hover {
      background: var(--color-hover);
    }

    &.is-checked {
      background: var(--color-brand-soft);
    }

    &.is-disabled,
    &.is-disabled:hover {
      background: transparent;
    }
  }

  :deep(.el-radio__label),
  :deep(.el-checkbox__label) {
    padding-left: 10px;
    font-size: 14px;
    line-height: inherit;
    word-break: break-word;
  }

  // 选中行底色为浅金色，文字保持正文色，避免金色文字压金色底影响辨识
  :deep(.el-radio.is-checked) .el-radio__label,
  :deep(.el-checkbox.is-checked) .el-checkbox__label {
    color: var(--color-text);
  }
}
</style>
