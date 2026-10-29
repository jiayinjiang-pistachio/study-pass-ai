/** 学习测评：题型与后端 /learning-workflows 契约对齐 */

export const QuizQuestionType = {
  Radio: 'radio',
  Checkbox: 'checkbox',
  Textarea: 'textarea',
} as const
export type QuizQuestionType =
  (typeof QuizQuestionType)[keyof typeof QuizQuestionType]

export interface QuizOption {
  key: string
  text: string
}

/** 后端 /start 与历史消息 response_payload 中归一化后的题目结构 */
export interface QuizQuestion {
  questionId: number
  type: QuizQuestionType
  stem: string
  options: QuizOption[]
}

/** 提交作答：字段名与后端 answers 一致（snake_case） */
export interface QuizAnswer {
  question_id: number
  value: string | string[]
}

export interface QuizEvaluationItem {
  questionId: number
  correct: boolean
  comment: string
}

/** 提交作答后的评分结果（后端 /submit 出参） */
export interface QuizSubmitResult {
  runId: string
  status: string
  score: number
  evaluation: QuizEvaluationItem[]
  weaknesses: string[]
  review: string
}
