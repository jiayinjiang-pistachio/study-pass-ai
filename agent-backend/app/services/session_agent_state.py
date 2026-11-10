"""业务层：会话级调度上下文（Redis 优先，MySQL 兜底）。

记录当前会话最近一次调度结果与最近一次测评 / 面试，供总控解析指代
（「刚才那套题」「复盘这次面试」）以及判断笔记 / 评测的前置数据。

Redis 只做加速：未命中、过期或不可用时回源 workflow_runs / interviews，
失败只记日志，不阻断请求。所有查询都带 user_id，天然隔离用户数据。
"""

import json
import logging
import time
from typing import Any

from ..core import redis_client
from ..db import interview_repo, workflow_run_repo

logger = logging.getLogger(__name__)

STATE_TTL_SECONDS = 8 * 3600
KEY_PREFIX = "agent:session"
WORKFLOW_TYPE_LEARNING_QUIZ = "learning_quiz"
STATUS_COMPLETED = "completed"


def _key(user_id: int, session_id: int) -> str:
    """调度上下文 key：按用户 + 会话隔离。"""
    return f"{KEY_PREFIX}:{user_id}:{session_id}"


def _empty_state() -> dict[str, Any]:
    return {
        "last_intent": None,
        "last_agent": None,
        "last_run_id": None,
        "last_run_status": None,
        "last_completed_run_id": None,
        "last_interview_id": None,
        "last_message_id": None,
        "updated_at": 0,
    }


def _from_db(user_id: int, session_id: int) -> dict[str, Any]:
    """回源数据库：最近一次运行、最近一次已完成测评与最近一次面试。"""
    state = _empty_state()

    run = workflow_run_repo.get_latest_for_session(user_id, session_id)
    if run is not None:
        state["last_run_id"] = run["run_id"]
        state["last_run_status"] = run["status"]

    completed = workflow_run_repo.get_latest_for_session(
        user_id,
        session_id,
        workflow_type=WORKFLOW_TYPE_LEARNING_QUIZ,
        status=STATUS_COMPLETED,
    )
    if completed is not None:
        state["last_completed_run_id"] = completed["run_id"]

    interview = interview_repo.get_latest_for_session(user_id, session_id)
    if interview is not None:
        state["last_interview_id"] = interview["id"]

    state["updated_at"] = int(time.time())
    return state


def _read_cache(user_id: int, session_id: int) -> dict[str, Any] | None:
    """读取 Redis 缓存；未命中、脏数据或 Redis 异常返回 None。"""
    try:
        raw = redis_client.get_client().get(_key(user_id, session_id))
    except Exception:
        logger.debug("调度上下文读取失败，回源数据库", exc_info=True)
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def get_state(user_id: int, session_id: int) -> dict[str, Any]:
    """返回会话调度上下文：数据库为事实来源，Redis 补充最近调度信息。"""
    state = _from_db(user_id, session_id)
    cached = _read_cache(user_id, session_id)
    if cached:
        for key in ("last_intent", "last_agent", "last_message_id"):
            if cached.get(key) is not None:
                state[key] = cached[key]
    return state


def record_dispatch(
    user_id: int,
    session_id: int,
    *,
    agent: str,
    intent: str | None = None,
    run_id: str | None = None,
    completed_run_id: str | None = None,
    interview_id: int | None = None,
    message_id: int | None = None,
) -> None:
    """记录一次调度结果；Redis 写失败只记日志，不影响本轮响应。"""
    state = get_state(user_id, session_id)
    state.update(
        {
            "last_agent": agent,
            "updated_at": int(time.time()),
        }
    )
    if intent is not None:
        state["last_intent"] = intent
    if run_id is not None:
        state["last_run_id"] = run_id
        state["last_run_status"] = None
    if completed_run_id is not None:
        state["last_completed_run_id"] = completed_run_id
    if interview_id is not None:
        state["last_interview_id"] = interview_id
    if message_id is not None:
        state["last_message_id"] = message_id

    try:
        redis_client.get_client().set(
            _key(user_id, session_id),
            json.dumps(state, ensure_ascii=False),
            ex=STATE_TTL_SECONDS,
        )
    except Exception:
        logger.info("调度上下文写入失败（不影响本轮调度）", exc_info=True)
