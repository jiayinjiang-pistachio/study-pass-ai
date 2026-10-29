import { request } from './request'
import type {
  QuizAnswer,
  QuizEvaluationItem,
  QuizSubmitResult,
} from '@/types/quiz'

interface RawEvaluationItem {
  question_id?: number
  correct?: boolean
  comment?: string
}

interface RawSubmitResult {
  run_id?: string
  status?: string
  score?: number
  evaluation?: RawEvaluationItem[]
  weaknesses?: unknown
  review?: string
}

function toEvaluation(value: unknown): QuizEvaluationItem[] {
  if (!Array.isArray(value)) return []
  const items: QuizEvaluationItem[] = []
  for (const raw of value) {
    if (typeof raw !== 'object' || raw === null) continue
    const item = raw as RawEvaluationItem
    if (typeof item.question_id !== 'number') continue
    items.push({
      questionId: item.question_id,
      correct: item.correct === true,
      comment: typeof item.comment === 'string' ? item.comment : '',
    })
  }
  return items
}

function toStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.filter((item): item is string => typeof item === 'string')
}

/** 提交作答并获取评分：POST /learning-workflows/{run_id}/submit */
export async function submitLearningQuiz(
  runId: string,
  answers: QuizAnswer[],
): Promise<QuizSubmitResult> {
  const data = await request<RawSubmitResult>(
    `/learning-workflows/${encodeURIComponent(runId)}/submit`,
    { method: 'POST', body: { answers } },
  )
  return {
    runId: typeof data.run_id === 'string' && data.run_id ? data.run_id : runId,
    status: typeof data.status === 'string' ? data.status : '',
    score: typeof data.score === 'number' ? data.score : 0,
    evaluation: toEvaluation(data.evaluation),
    weaknesses: toStringList(data.weaknesses),
    review: typeof data.review === 'string' ? data.review : '',
  }
}
