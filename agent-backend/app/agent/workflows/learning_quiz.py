"""学习测评工作流图：出题 → 等待作答 → 评分 → 完成。

跨两次 HTTP 请求执行同一张图：
- 启动时图跑到 `wait_user_answer` 的 `interrupt()` 暂停，执行现场存入 checkpoint；
- 提交时用 `Command(resume=answers)` 从暂停点继续评分并完成。

题目只返回题干与选项，标准答案不落库、不返回前端；评分由模型在提交时完成。
提示词中的 JSON 示例含大括号，必须作为静态 `SystemMessage` 传入。
"""

import json
import logging
from functools import lru_cache
from typing import Any, TypedDict

from fastapi import status
from langchain_core.messages import SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from ...core.exceptions import BusinessException
from ...core.retry import run_with_retry
from ...services import prompt_template_service
from ...services.ai.json_utils import parse_json_object
from ...services.ai.llm import get_chat_model
from .checkpoint import get_workflow_checkpointer

logger = logging.getLogger(__name__)

WORKFLOW_TYPE_LEARNING_QUIZ = "learning_quiz"

STATUS_CREATED = "created"
STATUS_WAITING_ANSWER = "waiting_answer"
STATUS_GRADING = "grading"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

DEFAULT_QUESTION_COUNT = 5
MAX_QUESTION_COUNT = 20

# 出题 / 评分提示词的作用域（复用现有智能体与已生效模板）
QUIZ_PROMPT_AGENT = "quiz_generate"
QUIZ_PROMPT_SCENE = "quiz"
EVAL_PROMPT_AGENT = "interview_evaluator"
EVAL_PROMPT_SCENE = "evaluation"

# 前端控件类型：radio=单选，checkbox=多选，textarea=简答
QUESTION_RADIO = "radio"
QUESTION_CHECKBOX = "checkbox"
QUESTION_TEXTAREA = "textarea"
QUESTION_TYPES = frozenset({QUESTION_RADIO, QUESTION_CHECKBOX, QUESTION_TEXTAREA})

STEM_MAX_CHARS = 500
OPTION_MAX_CHARS = 200
ANSWER_MAX_CHARS = 2000
COMMENT_MAX_CHARS = 500
REVIEW_MAX_CHARS = 2000
DISPLAY_TEXT_MAX_CHARS = 2000
DISPLAY_TEXT_MIN_CHARS = 10
WEAKNESS_MAX_ITEMS = 10
WEAKNESS_ITEM_MAX_CHARS = 50
OPTION_KEYS = "ABCDEFGH"


class LearningWorkflowState(TypedDict, total=False):
    """图的完整状态；checkpoint 保存执行现场，workflow_runs 只存业务快照。"""

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
    display_text: str
    status: str
    a2a_envelope: dict[str, Any]
    next_agent: str | None
    handoff_result: dict[str, Any]


# 数据库模板只有角色与出题 / 评分规则，JSON 结构由下面的静态契约补齐。
# 契约必须声明「优先于模板」，否则模板里的「参考答案 / 题量」等要求会污染输出。
DEFAULT_QUIZ_ROLE = """你是学习测评出题助手。请根据用户的学习需求出一套测评题，供前端表单渲染。"""

QUIZ_OUTPUT_RULES = """以下输出要求优先于上方模板中的冲突规则：

输出严格为 JSON 对象，结构如下：
{
  "questions": [
    {
      "type": "radio 或 checkbox 或 textarea",
      "stem": "题干（不含题号）",
      "options": [{"key": "A", "text": "选项内容"}]
    }
  ]
}

要求：
1. 题目数量严格等于用户要求的数量；type 只用 radio（单选）、checkbox（多选）、textarea（简答）；
2. radio 与 checkbox 各给 4 个选项；textarea 的 options 输出 []；
3. 不要输出答案、解析、题号，也不要输出 Markdown 代码块或额外说明；
4. 题干与选项使用中文，紧扣测评需求，难度适中。"""

DEFAULT_EVAL_ROLE = """你是学习测评评分助手。请根据题目与用户作答逐题评分，并给出整体复盘。"""

EVAL_OUTPUT_RULES = """以下输出要求优先于上方模板中的冲突规则：

输出严格为 JSON 对象，结构如下：
{
  "display_text": "面向用户的中文点评：先给结论，再指出主要问题与下一步",
  "score": "0-100 的整数总分",
  "items": [
    {"question_id": 1, "correct": true, "comment": "该题点评：对错原因 + 正确答案说明"}
  ],
  "weaknesses": ["薄弱点，1-5 条，每条不超过 50 字"],
  "review": "整体学习建议（200 字以内）"
}

要求：
1. display_text 必须是可直接展示的中文点评，不要为空；
2. items 必须覆盖每一道题，question_id 与输入一致；
3. radio / checkbox 按标准答案判定；textarea 按要点覆盖度判定，允许部分正确；
4. 点评要具体指出问题与改进方向，不要空泛；
5. 只输出 JSON，不要 Markdown 代码块或额外解释。"""


def _build_system_prompt(
    agent_name: str,
    scene: str,
    user_id: int | None,
    default_role: str,
    output_rules: str,
) -> str:
    """动态模板 + 静态 JSON 契约；模板不可用时降级为内置角色说明。"""
    try:
        base = prompt_template_service.get_rendered_prompt(agent_name, scene, user_id)
    except Exception:
        logger.warning(
            "学习测评提示词读取失败，使用内置提示词 | agent=%s scene=%s",
            agent_name,
            scene,
            exc_info=True,
        )
        base = ""
    base = (base or "").strip() or default_role
    return f"{base}\n\n{output_rules}"


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
            qtype = QUESTION_TEXTAREA
        options = (
            [] if qtype == QUESTION_TEXTAREA else _normalize_options(item.get("options"))
        )
        # 选择题选项不足时降级为简答题，避免前端渲染出无法作答的题目
        if qtype != QUESTION_TEXTAREA and len(options) < 2:
            qtype = QUESTION_TEXTAREA
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


def _normalize_display_text(
    raw: object,
    evaluation: list[dict],
    score: int,
    weaknesses: list[str],
    review: str,
) -> str:
    """优先用模型点评；过短 / 缺失时拼接得分、逐题点评与建议兜底。"""
    text = _clean_text(raw, DISPLAY_TEXT_MAX_CHARS)
    if len(text) >= DISPLAY_TEXT_MIN_CHARS:
        return text

    parts = [f"本次测评得分：{score} 分。"]
    parts.extend(item["comment"] for item in evaluation if item["comment"])
    if weaknesses:
        parts.append("薄弱点：" + "、".join(weaknesses) + "。")
    if review:
        parts.append("建议：" + review)
    return "\n".join(parts)[:DISPLAY_TEXT_MAX_CHARS]


def _normalize_evaluation(data: dict, quiz: list[dict]) -> dict:
    """把模型评分输出转成可入库结构；缺失的题目补占位点评。"""
    valid_ids = [question["question_id"] for question in quiz]
    items: list[dict] = []
    seen: set[int] = set()

    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        # 兼容模型沿用旧字段名的输出
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

    score = _normalize_score(data.get("score"), items)
    weaknesses = _normalize_weaknesses(data.get("weaknesses"))
    review = _clean_text(data.get("review"), REVIEW_MAX_CHARS) or "暂无整体建议"
    return {
        "score": score,
        "evaluation": items,
        "weaknesses": weaknesses,
        "review": review,
        "display_text": _normalize_display_text(
            data.get("display_text"), items, score, weaknesses, review
        ),
    }


def _option_keys(question: dict) -> set[str]:
    return {option["key"] for option in question.get("options") or []}


def _normalize_answer_value(question: dict, value: object) -> str | list[str]:
    """按题型校验并归一化答案；非法时抛 422。"""
    question_id = question["question_id"]
    qtype = question["type"]

    if qtype == QUESTION_TEXTAREA:
        text = _clean_text(value, ANSWER_MAX_CHARS)
        if not text:
            raise BusinessException(
                f"第 {question_id} 题未作答",
                http_status=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"question_id={question_id}",
            )
        return text

    if qtype == QUESTION_RADIO:
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


def normalize_answers(quiz: list[dict], answers: list) -> list[dict]:
    """校验作答完整性并按题目顺序归一化；保证评分的输入稳定。

    在恢复图之前执行：非法作答只返回 422，不改运行状态。
    """
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


def generate_quiz(state: LearningWorkflowState) -> dict:
    """调用模型生成题目；瞬时故障自动重试，耗尽后交业务层统一落库。"""
    return run_with_retry(lambda: _generate_quiz_once(state), node="generate_quiz")


def _generate_quiz_once(state: LearningWorkflowState) -> dict:
    """单次出题：模型输出经解析、归一化后返回可渲染题目。"""
    question_count = state.get("question_count") or DEFAULT_QUESTION_COUNT
    prompt = ChatPromptTemplate.from_messages(
        [
            SystemMessage(
                content=_build_system_prompt(
                    QUIZ_PROMPT_AGENT,
                    QUIZ_PROMPT_SCENE,
                    state.get("user_id"),
                    DEFAULT_QUIZ_ROLE,
                    QUIZ_OUTPUT_RULES,
                )
            ),
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
        "status": STATUS_WAITING_ANSWER,
    }


def wait_user_answer(state: LearningWorkflowState) -> dict:
    """暂停图等待作答；恢复时 interrupt() 返回 Command(resume=...) 携带的答案。"""
    answers = interrupt({"quiz": state.get("quiz") or []})
    return {"answers": answers, "status": STATUS_GRADING}


def evaluate_answer(state: LearningWorkflowState) -> dict:
    """调用模型完成评分；瞬时故障自动重试，耗尽后交业务层统一落库。"""
    return run_with_retry(lambda: _evaluate_answer_once(state), node="evaluate_answer")


def _evaluate_answer_once(state: LearningWorkflowState) -> dict:
    """单次评分：一次模型调用完成评分、逐题点评、薄弱点与整体建议。"""
    payload = json.dumps(
        {
            "quiz": state.get("quiz") or [],
            "answers": state.get("answers") or [],
        },
        ensure_ascii=False,
    )
    prompt = ChatPromptTemplate.from_messages(
        [
            SystemMessage(
                content=_build_system_prompt(
                    EVAL_PROMPT_AGENT,
                    EVAL_PROMPT_SCENE,
                    state.get("user_id"),
                    DEFAULT_EVAL_ROLE,
                    EVAL_OUTPUT_RULES,
                )
            ),
            ("human", "请评分并复盘以下测评：\n{payload}"),
        ]
    )
    raw = (
        (prompt | get_chat_model() | StrOutputParser()).invoke({"payload": payload})
        or ""
    )
    return _normalize_evaluation(parse_json_object(raw), state.get("quiz") or [])


def finalize_result(state: LearningWorkflowState) -> dict:
    """收尾节点：标记完成，并产出 A2A 信封表达接力意图（不直接调用下游）。

    只有存在薄弱点时才建议转给笔记智能体；无薄弱点则流程直接结束。
    """
    from app.agent.a2a import A2AEnvelope

    weaknesses = state.get("weaknesses") or []
    has_weakness = bool(weaknesses)
    envelope = A2AEnvelope(
        from_agent="learning_evaluator",
        payload_type="weak_points",
        payload={"score": state.get("score", 0), "weaknesses": weaknesses},
        next_agent="note_archiver" if has_weakness else None,
        confidence=0.9 if has_weakness else 0.4,
    )
    return {"status": STATUS_COMPLETED, "a2a_envelope": envelope.model_dump()}


@lru_cache(maxsize=1)
def build_learning_quiz_graph():
    """出题 → 等待作答 → 评分 → 完成的单图，挂载全局 checkpoint。"""
    graph = StateGraph(LearningWorkflowState)
    graph.add_node("generate_quiz", generate_quiz)
    graph.add_node("wait_user_answer", wait_user_answer)
    graph.add_node("evaluate_answer", evaluate_answer)
    graph.add_node("finalize_result", finalize_result)
    graph.add_edge(START, "generate_quiz")
    graph.add_edge("generate_quiz", "wait_user_answer")
    graph.add_edge("wait_user_answer", "evaluate_answer")
    graph.add_edge("evaluate_answer", "finalize_result")
    graph.add_edge("finalize_result", END)
    return graph.compile(checkpointer=get_workflow_checkpointer())
