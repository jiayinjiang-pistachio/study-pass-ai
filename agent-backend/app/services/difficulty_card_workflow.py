"""业务层：难点讲解知识卡工作流。

一次请求内完成：整理卡片原料（模型）→ 拼接绘图提示词（代码）→ Seedream 出图 →
MinIO 永久存储 + resources 去重 → 写入带 resource_id 的会话图片消息。
Agent 只负责整理原料，接口 / 数据库 / 出图 API 均由本层编排。
"""

import logging
import time
import uuid
from typing import Any

from fastapi import status

from ..agent.agents.difficulty_learner import (
    DifficultyLearnerAgent,
    build_image_prompt,
)
from ..core import minio_client
from ..core.exceptions import BusinessException, SystemException
from ..core.retry import RetryExhaustedError
from ..db import message_repo, session_repo, workflow_run_repo
from . import seedream_service, upload_service_minio

logger = logging.getLogger(__name__)

WORKFLOW_TYPE_DIFFICULTY_CARD = "difficulty_card"
AGENT_NAME = "difficulty_learner"

STATUS_GENERATING = "generating"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

SESSION_MODE_INTERVIEW = 1
# 1=知识精讲：知识卡以图片形式回显在会话中
SELECT_MODE_KNOWLEDGE = 1
RECENT_QA_LIMIT = 6
QA_CONTEXT_MAX_CHARS = 4000
ERROR_MESSAGE_MAX_CHARS = 2000

CARD_MESSAGE_TEXT_TEMPLATE = "已生成知识卡「{title}」，点击查看大图。"

__all__ = [
    "WORKFLOW_TYPE_DIFFICULTY_CARD",
    "start_difficulty_card",
]


def _recent_qa_context(session: dict) -> str:
    """面试会话取最近几轮问答作为卡片背景；学习会话不额外读取历史。"""
    if session.get("session_mode") != SESSION_MODE_INTERVIEW:
        return ""

    rows = message_repo.list_recent_completed(session["id"], RECENT_QA_LIMIT)
    parts: list[str] = []
    for row in rows:
        question = (row.get("request_text") or "").strip()
        answer = (row.get("response_text") or "").strip()
        if question:
            parts.append(f"用户：{question}")
        if answer:
            parts.append(f"助手：{answer}")
    text = "\n".join(parts)
    # 超长时保留最近的内容，避免早期寒暄挤占上下文
    return text[-QA_CONTEXT_MAX_CHARS:]


def _mark_failed(
    run_id: str, state: dict[str, Any], exc: Exception, *, node: str
) -> None:
    """统一失败落库；写库失败不掩盖原始异常。"""
    message = str(exc)[:ERROR_MESSAGE_MAX_CHARS]
    failed_state = {
        **state,
        "status": STATUS_FAILED,
        "error_node": node,
        "error_message": message,
    }
    try:
        workflow_run_repo.update(
            run_id,
            {
                "status": STATUS_FAILED,
                "state_json": failed_state,
                "error_message": message,
            },
        )
    except Exception:
        logger.warning(
            "记录知识卡失败状态出错 | run_id=%s node=%s", run_id, node, exc_info=True
        )


def _as_system_error(exc: Exception) -> SystemException:
    """把配置缺失 / 外部服务失败统一转成 503 或 502。"""
    cause = exc.last_error if isinstance(exc, RetryExhaustedError) else exc
    if isinstance(cause, RuntimeError):
        return SystemException(
            "知识卡服务暂不可用",
            http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(cause),
        )
    if isinstance(cause, SystemException):
        return cause
    return SystemException(
        "知识卡生成失败，请稍后重试",
        http_status=status.HTTP_502_BAD_GATEWAY,
        detail=str(cause),
    )


def _save_card_message(
    user_id: int,
    session_id: int,
    run_id: str,
    request_text: str,
    title: str,
    resource: dict,
) -> dict:
    """写入一条带图片 resource_id 的消息，历史读取时按 resource_id 续签 URL。"""
    segment = {
        "type": "image",
        "resource_id": resource["id"],
        "file_name": resource["file_name"],
    }
    return message_repo.insert(
        {
            "user_id": user_id,
            "session_id": session_id,
            "select_mode": SELECT_MODE_KNOWLEDGE,
            "request_id": f"{run_id}:card",
            "request_text": request_text,
            "response_text": CARD_MESSAGE_TEXT_TEMPLATE.format(title=title),
            "response_segments": [segment],
            "status": 1,
        }
    )


def start_difficulty_card(
    user_id: int, session_id: int, request_text: str
) -> dict:
    """执行知识卡流水线；返回 run_id、状态与知识卡基础信息。"""
    session = session_repo.get_for_user(session_id, user_id)
    if session is None:
        raise BusinessException(
            "会话不存在",
            http_status=status.HTTP_404_NOT_FOUND,
            detail=f"session_id={session_id} user_id={user_id}",
        )

    run_id = str(uuid.uuid4())
    state: dict[str, Any] = {
        "run_id": run_id,
        "user_id": user_id,
        "session_id": session_id,
        "request_text": request_text,
        "status": STATUS_GENERATING,
    }
    workflow_run_repo.insert(
        {
            "run_id": run_id,
            "user_id": user_id,
            "session_id": session_id,
            "workflow_type": WORKFLOW_TYPE_DIFFICULTY_CARD,
            "status": STATUS_GENERATING,
            "state_json": state,
        }
    )

    try:
        qa_context = _recent_qa_context(session)
        card = DifficultyLearnerAgent().prepare_card(
            user_id, request_text, qa_context
        )
        image_prompt = build_image_prompt(card)
        image_bytes = seedream_service.generate_image(image_prompt)
        saved = upload_service_minio.save_generated_image(
            user_id,
            image_bytes,
            file_name=f"知识卡-{card['title']}",
        )
        resource = saved["resource"]
        message = _save_card_message(
            user_id,
            session_id,
            run_id,
            request_text,
            card["title"],
            resource,
        )
    except Exception as exc:
        _mark_failed(run_id, state, exc, node="generate_card")
        raise _as_system_error(exc) from exc

    image_url = ""
    try:
        image_url = (
            minio_client.presigned_url_for_storage_path(resource["storage_path"])
            or ""
        )
    except Exception:
        # 预签名失败不影响已落库的图片：历史消息读取时会再次尝试续签
        logger.warning("知识卡预签名失败 | resource_id=%s", resource["id"], exc_info=True)

    completed_state = {
        **state,
        "status": STATUS_COMPLETED,
        "card": card,
        "image_prompt": image_prompt,
        "resource_id": resource["id"],
        "message_id": message["id"],
        "image_reused": not saved["created"],
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
        "知识卡已生成 | user_id=%s session_id=%s run_id=%s resource_id=%s reused=%s",
        user_id,
        session_id,
        run_id,
        resource["id"],
        not saved["created"],
    )
    return {
        "session_id": session_id,
        "run_id": run_id,
        "status": STATUS_COMPLETED,
        "title": card["title"],
        "resource_id": resource["id"],
        "image_url": image_url,
    }
