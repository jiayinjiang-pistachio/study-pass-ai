"""业务层：面试复盘智能体。

读取会话内最近一次已结束的语音面试（qa_object 非空），用
`interview_evaluator/evaluation` 生效模板 + 静态 JSON 契约生成
`{score, strengths, weaknesses, review}`，并写入一条幂等的会话消息。

消息先以 status=0 占位再回写结果，保证「结束面试自动复盘」与用户手动
触发复盘并发时不会重复落库；模型失败只把该消息置为失败，不影响面试结果。
"""

import json
import logging
import threading
from typing import Any

from fastapi import status
from langchain_core.messages import SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from ..core.exceptions import BusinessException, SystemException
from ..core.retry import RetryExhaustedError, run_with_retry
from ..db import interview_repo, message_repo
from . import prompt_template_service
from .ai.json_utils import parse_json_object
from .ai.llm import get_chat_model

logger = logging.getLogger(__name__)

AGENT_NAME = "interview_evaluator"
PROMPT_AGENT = "interview_evaluator"
PROMPT_SCENE = "evaluation"

SELECT_MODE_INTERVIEW_REVIEW = 5
MSG_STATUS_GENERATING = 0
MSG_STATUS_DONE = 1
MSG_STATUS_FAILED = 2

MAX_LIST_ITEMS = 5
ITEM_MAX_CHARS = 50
REVIEW_MAX_CHARS = 2000
DEFAULT_REVIEW = "结合本次暴露的薄弱点继续练习，下次回答时先给结论再展开细节。"

DEFAULT_EVAL_ROLE = """你是面试复盘助手。请根据本次模拟面试的完整问答记录，评估候选人的表现并给出可执行的改进建议。"""

OUTPUT_RULES = """以下输出要求优先于上方模板中的冲突规则：

输出严格为 JSON 对象，结构如下：
{
  "score": "0-100 的整数总分",
  "strengths": ["表现亮点，1-5 条，每条不超过 50 字"],
  "weaknesses": ["主要薄弱点，1-5 条，每条不超过 50 字"],
  "review": "整体复盘与改进建议（200 字以内）"
}

要求：
1. 只依据问答记录判断，不要编造候选人没有说过的内容；
2. 亮点与薄弱点各至少 1 条，尽量具体到知识深度、表达结构或项目细节；
3. review 要给出下一步可执行的练习方向；
4. 只输出 JSON，不要 Markdown 代码块或额外解释。"""

# 占位消息的创建必须原子化：自动复盘与用户手动触发可能同时到达
_CREATE_LOCK = threading.Lock()


def _clean_text(value: object, limit: int | None = None) -> str:
    """把任意值转成单行文本；空白值返回空串。"""
    if value is None:
        return ""
    text = " ".join(str(value).split())
    return text[:limit] if limit else text


def _string_list(value: object) -> list[str]:
    """只保留非空字符串项，并限制条数与单条长度。"""
    if not isinstance(value, (list, tuple)):
        return []
    items: list[str] = []
    for raw in value:
        text = _clean_text(raw, ITEM_MAX_CHARS)
        if text and text not in items:
            items.append(text)
        if len(items) >= MAX_LIST_ITEMS:
            break
    return items


def _normalize_score(value: object) -> int:
    """把模型输出归一为 0..100 的整数；非法值视为输出格式错误。"""
    if isinstance(value, bool):
        raise ValueError("score 不是整数")
    try:
        score = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("score 不是整数") from exc
    return max(0, min(100, score))


def _normalize_evaluation(data: dict) -> dict[str, Any]:
    """只接受契约中的字段；空列表允许，review 缺失时用默认建议兜底。"""
    return {
        "score": _normalize_score(data.get("score")),
        "strengths": _string_list(data.get("strengths")),
        "weaknesses": _string_list(data.get("weaknesses")),
        "review": _clean_text(data.get("review"), REVIEW_MAX_CHARS) or DEFAULT_REVIEW,
    }


def _build_system_prompt(user_id: int) -> str:
    """生效模板 + 静态 JSON 契约；模板不可用时降级为内置角色说明。"""
    try:
        base = prompt_template_service.get_rendered_prompt(
            PROMPT_AGENT, PROMPT_SCENE, user_id
        )
    except Exception:
        logger.warning(
            "面试复盘提示词读取失败，使用内置提示词 | agent=%s scene=%s",
            PROMPT_AGENT,
            PROMPT_SCENE,
            exc_info=True,
        )
        base = ""
    return f"{(base or '').strip() or DEFAULT_EVAL_ROLE}\n\n{OUTPUT_RULES}"


def _generate_evaluation(
    user_id: int, interview: dict, qa_object: list[dict]
) -> dict[str, Any]:
    """一次模型调用生成复盘 JSON；配置缺失 503，模型 / 解析失败 502。"""
    prompt = ChatPromptTemplate.from_messages(
        [
            SystemMessage(content=_build_system_prompt(user_id)),
            ("human", "以下是本次模拟面试的完整问答记录，请生成复盘：\n{payload}"),
        ]
    )
    payload = json.dumps(
        {
            "interview_duration": interview.get("interview_duration") or 0,
            "qa_count": len(qa_object),
            "qa_object": qa_object,
        },
        ensure_ascii=False,
    )

    try:
        raw = run_with_retry(
            lambda: (prompt | get_chat_model() | StrOutputParser()).invoke(
                {"payload": payload}
            )
            or "",
            node=AGENT_NAME,
        )
    except RetryExhaustedError as exc:
        if isinstance(exc.last_error, RuntimeError):
            raise SystemException(
                "AI 服务未配置，面试复盘暂不可用",
                http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"interview_id={interview.get('id')}",
            ) from exc
        raise SystemException(
            "面试复盘生成失败，请稍后重试",
            http_status=status.HTTP_502_BAD_GATEWAY,
            detail=f"interview_id={interview.get('id')}",
        ) from exc

    try:
        return _normalize_evaluation(parse_json_object(raw))
    except ValueError as exc:
        raise SystemException(
            "面试复盘生成失败，请稍后重试",
            http_status=status.HTTP_502_BAD_GATEWAY,
            detail=f"interview_id={interview.get('id')} error={exc}",
        ) from exc


def _display_text(evaluation: dict[str, Any]) -> str:
    """面向聊天的纯文本复盘；结构化数据另存 response_payload 供前端卡片渲染。"""
    lines = [f"本次面试复盘评分：{evaluation['score']}/100。"]
    if evaluation["strengths"]:
        lines.append("\n【亮点】")
        lines.extend(f"- {item}" for item in evaluation["strengths"])
    if evaluation["weaknesses"]:
        lines.append("\n【薄弱点】")
        lines.extend(f"- {item}" for item in evaluation["weaknesses"])
    lines.append("\n【改进建议】")
    lines.append(evaluation["review"])
    return "\n".join(lines)


def _request_id(interview_id: int) -> str:
    """同一面试只生成一份复盘；request_id 兼作幂等键。"""
    return f"interview:{interview_id}:evaluation"


def _load_or_create_message(
    user_id: int, session_id: int, interview_id: int
) -> dict:
    """已有完成 / 失败消息则复用；正在生成时拒绝并发重复请求。"""
    request_id = _request_id(interview_id)
    with _CREATE_LOCK:
        existing = message_repo.get_by_request_id(request_id, user_id)
        if existing is not None:
            if existing["status"] == MSG_STATUS_GENERATING:
                raise BusinessException(
                    "面试复盘正在生成，请稍后刷新查看",
                    http_status=status.HTTP_409_CONFLICT,
                    detail=f"interview_id={interview_id}",
                )
            return existing
        return message_repo.insert(
            {
                "user_id": user_id,
                "session_id": session_id,
                "select_mode": SELECT_MODE_INTERVIEW_REVIEW,
                "request_id": request_id,
                "request_text": "面试复盘",
                "response_text": "正在生成面试复盘…",
                "status": MSG_STATUS_GENERATING,
            }
        )


def _payload_from_message(message: dict, interview: dict) -> dict[str, Any]:
    """从已落库消息提取 task.payload；载荷异常时按完成文本兜底。"""
    payload = message.get("response_payload")
    if not isinstance(payload, dict) or payload.get("type") != "interview_evaluation":
        payload = {}
    return {
        "run_id": f"interview:{interview['id']}",
        "interview_id": interview["id"],
        "status": "completed",
        "score": payload.get("score"),
        "strengths": payload.get("strengths") or [],
        "weaknesses": payload.get("weaknesses") or [],
        "review": payload.get("review") or "",
        "message_id": message["id"],
    }


class InterviewEvaluationService:
    """面试复盘生成与会话消息落库；不负责触发（由总控 / 结束接口编排）。"""

    def evaluate_session(self, user_id: int, session_id: int) -> dict[str, Any]:
        """读取最近一次已结束面试并生成复盘；返回 task.payload 结构。"""
        interview = interview_repo.get_latest_completed_for_session(
            user_id, session_id
        )
        if interview is None:
            raise BusinessException(
                "当前会话还没有已结束的面试，暂时无法复盘",
                http_status=status.HTTP_409_CONFLICT,
                detail=f"session_id={session_id} user_id={user_id}",
            )

        qa_object = [
            item for item in interview.get("qa_object") or [] if isinstance(item, dict)
        ]
        if not qa_object:
            raise BusinessException(
                "本次面试没有问答记录，暂时无法复盘",
                http_status=status.HTTP_409_CONFLICT,
                detail=f"interview_id={interview['id']}",
            )

        message = _load_or_create_message(user_id, session_id, interview["id"])
        if message["status"] == MSG_STATUS_DONE:
            return _payload_from_message(message, interview)

        try:
            evaluation = _generate_evaluation(user_id, interview, qa_object)
        except Exception:
            message_repo.update_task_result(
                message["id"],
                "面试复盘生成失败，请稍后重试。",
                None,
                MSG_STATUS_FAILED,
            )
            raise

        payload = {
            "type": "interview_evaluation",
            "interview_id": interview["id"],
            **evaluation,
        }
        message_repo.update_task_result(
            message["id"], _display_text(evaluation), payload, MSG_STATUS_DONE
        )

        logger.info(
            "面试复盘已生成 | interview_id=%s user_id=%s session_id=%s score=%s",
            interview["id"],
            user_id,
            session_id,
            evaluation["score"],
        )
        return {
            "run_id": f"interview:{interview['id']}",
            "interview_id": interview["id"],
            "status": "completed",
            "score": evaluation["score"],
            "strengths": evaluation["strengths"],
            "weaknesses": evaluation["weaknesses"],
            "review": evaluation["review"],
            "message_id": message["id"],
        }


def evaluate_session_background(user_id: int, session_id: int) -> None:
    """结束面试后的后台自动复盘；失败只记日志，不影响面试结果。"""
    try:
        InterviewEvaluationService().evaluate_session(user_id, session_id)
    except Exception:
        logger.warning(
            "自动面试复盘失败（不影响面试结果）| user_id=%s session_id=%s",
            user_id,
            session_id,
            exc_info=True,
        )
