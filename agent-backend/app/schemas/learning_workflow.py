"""校验层：学习测评工作流的请求 / 响应模型。

只约束 HTTP 契约；题目归一化与作答合法性（选项是否存在）在业务层完成，
因为校验层拿不到生成后的 quiz。
"""

from typing import Annotated, Any

from pydantic import BaseModel, Field, StringConstraints

# 与 app/agent/workflows/learning_quiz.py 的题目数量上限保持一致
DEFAULT_QUESTION_COUNT = 5
MAX_QUESTION_COUNT = 20

RequestText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20000)
]
ProviderName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)
]


class LearningWorkflowStartIn(BaseModel):
    """发起学习测评：描述需求，后端生成结构化题目。"""

    session_id: int = Field(..., ge=1, description="所属会话 ID")
    request_text: RequestText = Field(..., description="测评需求（学什么、测什么）")
    question_count: int | None = Field(
        None,
        ge=1,
        le=MAX_QUESTION_COUNT,
        description=(
            f"题目数量，1..{MAX_QUESTION_COUNT}；缺省时从 request_text 提取"
            f"（如「出 3 道题」），仍无则 {DEFAULT_QUESTION_COUNT}"
        ),
    )
    provider: ProviderName | None = Field(
        None, description="模型服务商标识（仅记录，缺省取全局 LLM_PROVIDER）"
    )


class AnswerItem(BaseModel):
    """单题作答：单选题传字符串，多选题传字符串数组，简答题传字符串。"""

    question_id: int = Field(..., ge=1, description="题目 ID（由出题接口返回）")
    value: str | list[str] = Field(..., description="作答内容")


class LearningWorkflowSubmitIn(BaseModel):
    """提交整套作答：必须覆盖全部题目。"""

    answers: list[AnswerItem] = Field(
        ..., min_length=1, max_length=MAX_QUESTION_COUNT, description="逐题作答"
    )


class QuizOptionOut(BaseModel):
    key: str = Field(..., description="选项标识，如 A / B")
    text: str = Field(..., description="选项内容")


class QuizQuestionOut(BaseModel):
    question_id: int = Field(..., description="题目 ID")
    type: str = Field(
        ..., description="前端控件类型：radio / checkbox / textarea"
    )
    stem: str = Field(..., description="题干")
    options: list[QuizOptionOut] = Field(
        default_factory=list, description="选项；简答题为空数组"
    )


class LearningWorkflowStartOut(BaseModel):
    run_id: str = Field(..., description="工作流运行 ID")
    status: str = Field(..., description="流程状态，出题成功为 waiting_answer")
    quiz: list[QuizQuestionOut] = Field(..., description="结构化题目")


class EvaluationItemOut(BaseModel):
    question_id: int = Field(..., description="题目 ID")
    correct: bool = Field(..., description="是否答对")
    comment: str = Field(..., description="逐题点评")


class HandoffResultOut(BaseModel):
    """A2A 统一派发结果：completed / pending / rejected / failed。"""

    status: str = Field(..., description="派发状态")
    from_agent: str | None = Field(default=None, description="信封产出方")
    next_agent: str | None = Field(default=None, description="校验通过的接力目标")
    result: dict[str, Any] | None = Field(default=None, description="handler 返回值")
    reason: str | None = Field(default=None, description="未完成派发的原因")


class LearningWorkflowSubmitOut(BaseModel):
    run_id: str = Field(..., description="工作流运行 ID")
    status: str = Field(..., description="流程状态，提交成功为 completed")
    score: int = Field(..., description="总分 0..100")
    evaluation: list[EvaluationItemOut] = Field(..., description="逐题评分与点评")
    weaknesses: list[str] = Field(..., description="薄弱点")
    review: str = Field(..., description="整体学习建议")
    next_agent: str | None = Field(
        default=None, description="校验通过的接力目标；None 表示流程结束"
    )
    handoff_result: HandoffResultOut | None = Field(
        default=None, description="A2A 派发结果；handler 未实现时为 pending"
    )


class LearningWorkflowDetailOut(BaseModel):
    run_id: str = Field(..., description="工作流运行 ID")
    status: str = Field(..., description="流程状态")
    state: dict[str, Any] = Field(..., description="完整工作流状态")
    next_agent: str | None = Field(
        default=None, description="校验通过的接力目标；None 表示流程结束"
    )
