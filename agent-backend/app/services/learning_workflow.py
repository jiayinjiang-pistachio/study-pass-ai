"""业务层：最小学习测评工作流（LangGraph 编排 + workflow_runs 持久化）。

两次 HTTP 请求构成闭环：
1. start：生成结构化题目（quiz_ready），状态落 workflow_runs.state_json；
2. submit：按 run_id 恢复题目，评分 + 逐题点评 + 薄弱点 + 建议（completed）。

图结构：
- 启动图：prepare_learning_context → generate_quiz → END
- 提交图：evaluate_and_review → END

题目只返回题干与选项，标准答案不落库、不返回前端；评分由模型在提交时完成。
"""

import json
import logging
import time
import uuid
from functools import lru_cache
from typing import TypedDict

from fastapi import status
from langchain_core.messages import SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, START, StateGraph

from ..core.config import LLM_PROVIDER
from ..core.exceptions import BusinessException, SystemException
from ..db import session_repo, workflow_run_repo
from ..schemas.learning_workflow import LearningWorkflowSubmitIn
from .ai.json_utils import parse_json_object
from .ai.llm import get_chat_model

logger = logging.getLogger(__name__)

WORKFLOW_TYPE_LEARNING_QUIZ = "learning_quiz"

STATUS_RUNNING = "running"
STATUS_QUIZ_READY = "quiz_ready"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

DEFAULT_QUESTION_COUNT = 5
MAX_QUESTION_COUNT = 20

QUESTION_SINGLE_CHOICE = "single_choice"
QUESTION_MULTIPLE_CHOICE = "multiple_choice"
QUESTION_SHORT_ANSWER = "short_answer"
QUESTION_TYPES = frozenset(
    {QUESTION_SINGLE_CHOICE, QUESTION_MULTIPLE_CHOICE, QUESTION_SHORT_ANSWER}
)

STEM_MAX_CHARS = 500
OPTION_MAX_CHARS = 200
ANSWER_MAX_CHARS = 2000
COMMENT_MAX_CHARS = 500
REVIEW_MAX_CHARS = 2000
WEAKNESS_MAX_ITEMS = 10
WEAKNESS_ITEM_MAX_CHARS = 50
ERROR_MESSAGE_MAX_CHARS = 2000
OPTION_KEYS = "ABCDEFGH"


class LearningWorkflowState(TypedDict, total=False):
    """学习测评工作流的完整状态（即 workflow_runs.state_json）。"""

    run_id: str
    user_id: int
    session_id: int
    request_text: str
    provider: str
    question_count: int
    quiz: list[dict]
    answers: list[dict]
    evaluation: list[dict]
    score: int
    weaknesses: list[str]
    review: str
    status: str


# JSON 示例含大括号，必须作为静态 SystemMessage 传入，避免被 ChatPromptTemplate
# 当成模板变量解析（同 long_term_memory 的处理）。
QUIZ_SYSTEM_PROMPT = """你是学习测评出题助手。请根据用户的学习需求出一套测评题，供前端表单渲染。

输出严格为 JSON 对象，结构如下：
{
  "questions": [
    {
      "type": "single_choice 或 multiple_choice 或 short_answer",
      "stem": "题干（不含题号）",
      "options": [{"key": "A", "text": "选项内容"}]
    }
  ]
}

要求：
1. 题目数量严格等于用户要求的数量，题型在三类之间分布，优先客观题；
2. single_choice 与 multiple_choice 各给 4 个选项；short_answer 的 options 输出 []；
3. 不要输出答案、解析、题号，也不要输出 Markdown 代码块或额外说明；
4. 题干与选项使用中文，紧扣测评需求，难度适中。"""

EVAL_SYSTEM_PROMPT = """你是学习测评评分助手。请根据题目与用户作答逐题评分，并给出整体复盘。

输出严格为 JSON 对象，结构如下：
{
  "score": "0-100 的整数总分",
  "evaluation": [
    {"question_id": 1, "correct": true, "comment": "该题点评：对错原因 + 正确答案说明"}
  ],
  "weaknesses": ["薄弱点，1-5 条，每条不超过 50 字"],
  "review": "整体学习建议（200 字以内）"
}

要求：
1. evaluation 必须覆盖每一道题，question_id 与输入一致；
2. 单选 / 多选按标准答案判定；简答按要点覆盖度判定，允许部分正确；
3. 点评要具体指出问题与改进方向，不要空泛；
4. 只输出 JSON，不要 Markdown 代码块或额外解释。"""


def _clean_text(value: object, limit: int) -> str:
    """去空白并截断；非字符串返回空串。"""
    if not isinstance(value, str):
        return ""
    return value.strip()[:limit]


def _normalize_options(raw: object) -> list[dict]:
    """清洗选项：去空、截断、补齐 A/B/C 键并去重。"""
    if not isinstance(raw, list):
        return []
    options: list[dict] = []
    used_keys: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = _clean_text(item.get("text"), OPTION_MAX_CHARS)
        if not text:
            continue
        key = _clean_text(item.get("key"), 2).upper()
        if not key or key in used_keys:
            key = OPTION_KEYS[len(options)]
        if key in used_keys:
            continue
        used_keys.add(key)
        options.append({"key": key, "text": text})
        if len(options) >= len(OPTION_KEYS):
            break
    return options


def _normalize_quiz(data: dict, question_count: int) -> list[dict]:
    """把模型输出转成前端可渲染的题目列表；无有效题目时抛 ValueError。"""
    raw_questions = data.get("questions")
    if not isinstance(raw_questions, list) or not raw_questions:
        raise ValueError("模型未生成题目")

    quiz: list[dict] = []
    for item in raw_questions:
        if len(quiz) >= question_count:
            break
        if not isinstance(item, dict):
            continue
        stem = _clean_text(item.get("stem"), STEM_MAX_CHARS)
        if not stem:
            continue

        qtype = item.get("type")
        if qtype not in QUESTION_TYPES:
            qtype = QUESTION_SHORT_ANSWER
        options = (
            [] if qtype == QUESTION_SHORT_ANSWER else _normalize_options(item.get("options"))
        )
        # 选择题选项不足时降级为简答题，避免前端渲染出无法作答的题目
        if qtype != QUESTION_SHORT_ANSWER and len(options) < 2:
            qtype = QUESTION_SHORT_ANSWER
            options = []

        quiz.append(
            {
                "question_id": len(quiz) + 1,
                "type": qtype,
                "stem": stem,
                "options": options,
            }
        )

    if not quiz:
        raise ValueError("模型生成的题目格式非法")
    return quiz


def _normalize_score(value: object, evaluation: list[dict]) -> int:
    """总分优先取模型输出，非法时按正确率回退到 0..100。"""
    score: int | None = None
    if isinstance(value, bool):
        score = None
    elif isinstance(value, int):
        score = value
    elif isinstance(value, float) and value.is_integer():
        score = int(value)
    elif isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            score = int(text)
    if score is None:
        correct = sum(1 for item in evaluation if item["correct"])
        return round(correct / len(evaluation) * 100) if evaluation else 0
    return max(0, min(100, score))


def _normalize_weaknesses(raw: object) -> list[str]:
    """薄弱点：字符串数组，去重、限长、限项数。"""
    if not isinstance(raw, list):
        return []
    result: list[str] = []
    for item in raw:
        text = _clean_text(item, WEAKNESS_ITEM_MAX_CHARS)
        if text and text not in result:
            result.append(text)
        if len(result) >= WEAKNESS_MAX_ITEMS:
            break
    return result


def _normalize_evaluation(data: dict, quiz: list[dict]) -> dict:
    """把模型评分输出转成可入库结构；缺失的题目补占位点评。"""
    valid_ids = [question["question_id"] for question in quiz]
    items: list[dict] = []
    seen: set[int] = set()

    raw_items = data.get("evaluation")
    if isinstance(raw_items, list):
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            question_id = item.get("question_id")
            if (
                isinstance(question_id, bool)
                or not isinstance(question_id, int)
                or question_id not in valid_ids
                or question_id in seen
            ):
                continue
            seen.add(question_id)
            items.append(
                {
                    "question_id": question_id,
                    "correct": bool(item.get("correct")),
                    "comment": _clean_text(item.get("comment"), COMMENT_MAX_CHARS)
                    or "（未提供点评）",
                }
            )

    for question_id in valid_ids:
        if question_id not in seen:
            items.append(
                {
                    "question_id": question_id,
                    "correct": False,
                    "comment": "（模型未给出该题点评）",
                }
            )
    items.sort(key=lambda item: item["question_id"])

    return {
        "score": _normalize_score(data.get("score"), items),
        "evaluation": items,
        "weaknesses": _normalize_weaknesses(data.get("weaknesses")),
        "review": _clean_text(data.get("review"), REVIEW_MAX_CHARS) or "暂无整体建议",
    }


def _option_keys(question: dict) -> set[str]:
    return {option["key"] for option in question.get("options") or []}


def _normalize_answer_value(question: dict, value: object) -> str | list[str]:
    """按题型校验并归一化答案；非法时抛 422。"""
    question_id = question["question_id"]
    qtype = question["type"]

    if qtype == QUESTION_SHORT_ANSWER:
        text = _clean_text(value, ANSWER_MAX_CHARS)
        if not text:
            raise BusinessException(
                f"第 {question_id} 题未作答",
                http_status=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"question_id={question_id}",
            )
        return text

    if qtype == QUESTION_SINGLE_CHOICE:
        key = _clean_text(value, 2).upper()
        if key not in _option_keys(question):
            raise BusinessException(
                f"第 {question_id} 题的选项非法",
                http_status=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"question_id={question_id} value={value!r}",
            )
        return key

    if not isinstance(value, list):
        raise BusinessException(
            f"第 {question_id} 题需要提交多个选项",
            http_status=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"question_id={question_id}",
        )
    keys: list[str] = []
    for raw in value:
        key = _clean_text(raw, 2).upper()
        if key not in _option_keys(question):
            raise BusinessException(
                f"第 {question_id} 题的选项非法",
                http_status=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"question_id={question_id} value={raw!r}",
            )
        if key not in keys:
            keys.append(key)
    if not keys:
        raise BusinessException(
            f"第 {question_id} 题未作答",
            http_status=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"question_id={question_id}",
        )
    return sorted(keys)


def _normalize_answers(quiz: list[dict], answers: list) -> list[dict]:
    """校验作答完整性并按题目顺序归一化；保证评分的输入稳定。"""
    by_id = {question["question_id"]: question for question in quiz}
    seen: set[int] = set()
    normalized: list[dict] = []

    for answer in answers:
        question_id = answer.question_id
        if question_id in seen:
            raise BusinessException(
                "同一题目不能重复作答",
                http_status=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"question_id={question_id}",
            )
        question = by_id.get(question_id)
        if question is None:
            raise BusinessException(
                f"题目 {question_id} 不存在",
                http_status=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"question_id={question_id}",
            )
        seen.add(question_id)
        normalized.append(
            {
                "question_id": question_id,
                "value": _normalize_answer_value(question, answer.value),
            }
        )

    missing = [qid for qid in by_id if qid not in seen]
    if missing:
        raise BusinessException(
            f"还有 {len(missing)} 道题未作答",
            http_status=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"missing={sorted(missing)}",
        )

    normalized.sort(key=lambda item: item["question_id"])
    return normalized


def _prepare_learning_context(state: LearningWorkflowState) -> dict:
    """轻量准备节点：仅标记流程进入生成阶段，不做外部调用。"""
    return {"status": STATUS_RUNNING}


def _generate_quiz(state: LearningWorkflowState) -> dict:
    """调用模型生成结构化题目，并归一化成前端可渲染的 JSON。"""
    question_count = state.get("question_count") or DEFAULT_QUESTION_COUNT
    prompt = ChatPromptTemplate.from_messages(
        [
            SystemMessage(content=QUIZ_SYSTEM_PROMPT),
            (
                "human",
                "测评需求：\n{request_text}\n\n题目数量：{question_count}",
            ),
        ]
    )
    raw = (
        (prompt | get_chat_model() | StrOutputParser())
        .invoke(
            {
                "request_text": state.get("request_text", ""),
                "question_count": question_count,
            }
        )
        or ""
    )
    return {
        "quiz": _normalize_quiz(parse_json_object(raw), question_count),
        "status": STATUS_QUIZ_READY,
    }


def _evaluate_and_review(state: LearningWorkflowState) -> dict:
    """一次模型调用完成评分、逐题点评、薄弱点与整体建议。"""
    payload = json.dumps(
        {
            "quiz": state.get("quiz") or [],
            "answers": state.get("answers") or [],
        },
        ensure_ascii=False,
    )
    prompt = ChatPromptTemplate.from_messages(
        [
            SystemMessage(content=EVAL_SYSTEM_PROMPT),
            ("human", "请评分并复盘以下测评：\n{payload}"),
        ]
    )
    raw = (
        (prompt | get_chat_model() | StrOutputParser()).invoke({"payload": payload})
        or ""
    )
    return _normalize_evaluation(parse_json_object(raw), state.get("quiz") or [])


@lru_cache(maxsize=1)
def build_start_graph():
    """启动图：prepare_learning_context → generate_quiz → END。"""
    graph = StateGraph(LearningWorkflowState)
    graph.add_node("prepare_learning_context", _prepare_learning_context)
    graph.add_node("generate_quiz", _generate_quiz)
    graph.add_edge(START, "prepare_learning_context")
    graph.add_edge("prepare_learning_context", "generate_quiz")
    graph.add_edge("generate_quiz", END)
    return graph.compile()


@lru_cache(maxsize=1)
def build_submit_graph():
    """提交图：evaluate_and_review → END。"""
    graph = StateGraph(LearningWorkflowState)
    graph.add_node("evaluate_and_review", _evaluate_and_review)
    graph.add_edge(START, "evaluate_and_review")
    graph.add_edge("evaluate_and_review", END)
    return graph.compile()


def _mark_failed(run_id: str, state: LearningWorkflowState, exc: Exception) -> None:
    """把失败状态与原因写回数据库；写库失败不能掩盖原始异常。"""
    failed_state = {**state, "status": STATUS_FAILED}
    try:
        workflow_run_repo.update(
            run_id,
            {
                "status": STATUS_FAILED,
                "state_json": failed_state,
                "error_message": str(exc)[:ERROR_MESSAGE_MAX_CHARS],
            },
        )
    except Exception:
        logger.warning("记录工作流失败状态出错 | run_id=%s", run_id, exc_info=True)


def _raise_workflow_error(
    run_id: str, state: LearningWorkflowState, exc: Exception, action: str
) -> None:
    """按错误类型转成 503（配置缺失）或 502（模型 / 解析失败）。"""
    _mark_failed(run_id, state, exc)
    if isinstance(exc, RuntimeError):
        raise SystemException(
            "学习测评服务暂不可用",
            http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    logger.error("学习测评%s失败 | run_id=%s", action, run_id, exc_info=True)
    raise SystemException(
        f"学习测评{action}失败，请稍后重试",
        http_status=status.HTTP_502_BAD_GATEWAY,
        detail=f"run_id={run_id} error={exc}",
    ) from exc


def start_learning_workflow(user_id: int, payload) -> dict:
    """校验会话归属 → 执行启动图 → 持久化题目并返回 quiz_ready。"""
    session = session_repo.get_for_user(payload.session_id, user_id)
    if session is None:
        raise BusinessException(
            "会话不存在",
            http_status=status.HTTP_404_NOT_FOUND,
            detail=f"session_id={payload.session_id} user_id={user_id}",
        )

    run_id = str(uuid.uuid4())
    state: LearningWorkflowState = {
        "run_id": run_id,
        "user_id": user_id,
        "session_id": payload.session_id,
        "request_text": payload.request_text,
        "provider": payload.provider or LLM_PROVIDER,
        "question_count": payload.question_count,
        "quiz": [],
        "answers": [],
        "evaluation": [],
        "score": 0,
        "weaknesses": [],
        "review": "",
        "status": STATUS_RUNNING,
    }
    workflow_run_repo.insert(
        {
            "run_id": run_id,
            "user_id": user_id,
            "session_id": payload.session_id,
            "workflow_type": WORKFLOW_TYPE_LEARNING_QUIZ,
            "status": STATUS_RUNNING,
            "state_json": state,
        }
    )

    try:
        result = build_start_graph().invoke(state)
    except Exception as exc:
        _raise_workflow_error(run_id, state, exc, "生成")

    quiz = result.get("quiz") or []
    saved_state = {**state, **result, "status": STATUS_QUIZ_READY}
    workflow_run_repo.update(
        run_id,
        {"status": STATUS_QUIZ_READY, "state_json": saved_state, "error_message": None},
    )
    logger.info(
        "学习测评已出题 | run_id=%s user_id=%s question_count=%s",
        run_id,
        user_id,
        len(quiz),
    )
    return {"run_id": run_id, "status": STATUS_QUIZ_READY, "quiz": quiz}


def submit_learning_workflow(
    user_id: int, run_id: str, payload: LearningWorkflowSubmitIn
) -> dict:
    """恢复题目 → 校验作答 → 执行提交图 → 持久化评分结果。"""
    row = workflow_run_repo.get_for_user(run_id, user_id)
    if row is None:
        raise BusinessException(
            "测评不存在",
            http_status=status.HTTP_404_NOT_FOUND,
            detail=f"run_id={run_id} user_id={user_id}",
        )
    if row["status"] == STATUS_COMPLETED:
        raise BusinessException(
            "该测评已提交，请勿重复提交",
            http_status=status.HTTP_409_CONFLICT,
            detail=f"run_id={run_id}",
        )
    if row["status"] != STATUS_QUIZ_READY:
        raise BusinessException(
            "当前测评状态不可提交",
            http_status=status.HTTP_409_CONFLICT,
            detail=f"run_id={run_id} status={row['status']}",
        )

    state: LearningWorkflowState = dict(row["state_json"] or {})
    quiz = state.get("quiz") or []
    if not quiz:
        raise BusinessException(
            "测评题目缺失，请重新发起测评",
            http_status=status.HTTP_409_CONFLICT,
            detail=f"run_id={run_id}",
        )
    answers = _normalize_answers(quiz, payload.answers)
    submit_state: LearningWorkflowState = {
        **state,
        "answers": answers,
        "status": STATUS_RUNNING,
    }

    try:
        result = build_submit_graph().invoke(submit_state)
    except Exception as exc:
        _raise_workflow_error(run_id, submit_state, exc, "评测")

    completed_state = {
        **submit_state,
        **result,
        "status": STATUS_COMPLETED,
    }
    workflow_run_repo.update(
        run_id,
        {
            "status": STATUS_COMPLETED,
            "state_json": completed_state,
            "error_message": None,
            "completed_at": int(time.time()),
        },
    )
    logger.info(
        "学习测评已完成 | run_id=%s user_id=%s score=%s",
        run_id,
        user_id,
        completed_state.get("score"),
    )
    return {
        "run_id": run_id,
        "status": STATUS_COMPLETED,
        "score": completed_state.get("score", 0),
        "evaluation": completed_state.get("evaluation", []),
        "weaknesses": completed_state.get("weaknesses", []),
        "review": completed_state.get("review", ""),
    }


def get_learning_workflow(user_id: int, run_id: str) -> dict:
    """按 run_id + user_id 查询运行详情；状态与完整 state 一并返回。"""
    row = workflow_run_repo.get_for_user(run_id, user_id)
    if row is None:
        raise BusinessException(
            "测评不存在",
            http_status=status.HTTP_404_NOT_FOUND,
            detail=f"run_id={run_id} user_id={user_id}",
        )
    return {
        "run_id": row["run_id"],
        "status": row["status"],
        "state": row["state_json"] or {},
    }
