/** 学习测评：载荷归一化与本地兜底文案（纯函数，不依赖组件与请求层） */

import { QuizQuestionType } from '@/types/quiz'
import type {
  QuizOption,
  QuizQuestion,
  QuizSubmitResult,
} from '@/types/quiz'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

/** 兼容扁平数组、{quiz}、{questions} 与 {quiz:{questions}} 四种形态 */
function extractList(value: unknown): unknown[] {
  if (Array.isArray(value)) return value
  if (!isRecord(value)) return []
  if (Array.isArray(value.quiz)) return value.quiz
  if (Array.isArray(value.questions)) return value.questions
  if (isRecord(value.quiz) && Array.isArray(value.quiz.questions)) {
    return value.quiz.questions
  }
  return []
}

function toOptions(value: unknown): QuizOption[] {
  if (!Array.isArray(value)) return []
  const options: QuizOption[] = []
  for (const item of value) {
    if (!isRecord(item)) continue
    const key = typeof item.key === 'string' ? item.key.trim() : ''
    const text = typeof item.text === 'string' ? item.text.trim() : ''
    if (key && text) options.push({ key, text })
  }
  return options
}

function toQuestion(raw: unknown): QuizQuestion | null {
  if (!isRecord(raw)) return null
  if (typeof raw.question_id !== 'number' || !Number.isFinite(raw.question_id)) {
    return null
  }
  const stem = typeof raw.stem === 'string' ? raw.stem.trim() : ''
  if (!stem) return null

  const options = toOptions(raw.options)
  // 选择题没有可选项时无法作答，降级为简答；未知题型同样按简答处理
  let type: QuizQuestionType = QuizQuestionType.Textarea
  if (options.length > 0) {
    if (raw.type === QuizQuestionType.Radio) type = QuizQuestionType.Radio
    else if (raw.type === QuizQuestionType.Checkbox) {
      type = QuizQuestionType.Checkbox
    }
  }

  return {
    questionId: raw.question_id,
    type,
    stem,
    options: type === QuizQuestionType.Textarea ? [] : options,
  }
}

/** 把后端 quiz 载荷归一化为可渲染的题目数组；非法数据返回空数组 */
export function normalizeQuizPayload(value: unknown): QuizQuestion[] {
  return extractList(value)
    .map(toQuestion)
    .filter((question): question is QuizQuestion => question !== null)
}

/** 从 "{run_id}:quiz" 取出 run_id；没有冒号时整体视为 run_id */
export function quizRunId(requestId: string | null | undefined): string | null {
  if (!requestId) return null
  const index = requestId.indexOf(':')
  const runId = (index === -1 ? requestId : requestId.slice(0, index)).trim()
  return runId || null
}

/** 刷新会话失败时的本地兜底点评：得分 + 逐题点评 + 薄弱点 + 建议 */
export function buildEvaluationText(result: QuizSubmitResult): string {
  const lines: string[] = [`本次测评得分：${result.score} 分。`]
  if (result.evaluation.length) {
    lines.push('', '逐题点评：')
    result.evaluation.forEach((item, index) => {
      const verdict = item.correct ? '正确' : '错误'
      const comment = item.comment ? `：${item.comment}` : ''
      lines.push(`${index + 1}. ${verdict}${comment}`)
    })
  }
  if (result.weaknesses.length) {
    lines.push('', `薄弱点：${result.weaknesses.join('、')}。`)
  }
  if (result.review) {
    lines.push('', `建议：${result.review}`)
  }
  return lines.join('\n')
}
