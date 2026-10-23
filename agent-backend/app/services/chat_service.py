"""业务层：流式 AI 对话（SSE）。

流程：校验会话归属 → 落库用户消息（status=0）→ 记忆层构建上下文 →
提示词层组装链路 → 模型层流式输出 → 回写回复正文与状态。

SSE 事件约定（每条 data 均为 JSON）：
- meta : {session_id, message_id, request_id}        流开始，告知落库后的消息 ID
- delta: {content}                                   增量文本
- done : {message_id, status}                        生成完成
- error: {code, message}                             生成失败（仍可保留部分内容）
"""

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import NamedTuple

from fastapi import status
from langchain_core.runnables import Runnable
from starlette.concurrency import run_in_threadpool

from ..core.exceptions import BusinessException, SystemException
from ..db import message_repo, resource_repo, session_repo
from ..schemas.chat import StreamChatIn
from .ai import memory, prompt_layer

logger = logging.getLogger(__name__)

STATUS_GENERATING = 0
STATUS_DONE = 1
STATUS_FAILED = 2

EVENT_META = "meta"
EVENT_DELTA = "delta"
EVENT_DONE = "done"
EVENT_ERROR = "error"


class StreamState(NamedTuple):
    """预处理结果：路由层先完成校验与落库，再交给流式生成器。"""

    session: dict
    message: dict
    context: dict
    chain: Runnable


def _get_owned_session(user_id: int, session_id: int) -> dict:
    """取当前用户的会话；不存在或不属于该用户统一 404。"""
    session = session_repo.get_for_user(session_id, user_id)
    if session is None:
        raise BusinessException(
            "会话不存在",
            http_status=status.HTTP_404_NOT_FOUND,
            detail=f"session_id={session_id} user_id={user_id}",
        )
    return session


def _ensure_segments_owned(user_id: int, payload: StreamChatIn) -> None:
    """附件只能引用当前用户自己的资源，防止越权读取他人文件。"""
    for segment in payload.request_segments:
        resource = resource_repo.get(segment.resource_id)
        if resource is None or resource["user_id"] != user_id:
            raise BusinessException(
                "附件不存在",
                http_status=status.HTTP_404_NOT_FOUND,
                detail=f"resource_id={segment.resource_id} user_id={user_id}",
            )


def _build_chain(session_mode: int, select_mode: int) -> Runnable:
    """组装链路；模型配置缺失属于系统问题，对外统一 503。"""
    try:
        return prompt_layer.build_chat_chain(session_mode, select_mode)
    except RuntimeError as exc:
        raise SystemException(
            "AI 服务未配置，请联系管理员",
            http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


def prepare_stream(
    user_id: int, session_id: int, payload: StreamChatIn
) -> StreamState:
    """校验会话与附件、落库用户消息、构建上下文。

    在返回 StreamingResponse 之前执行，因此 404 / 503 仍是标准 JSON 错误信封。
    """
    session = _get_owned_session(user_id, session_id)
    _ensure_segments_owned(user_id, payload)
    chain = _build_chain(session["session_mode"], payload.select_mode)

    segments = [segment.model_dump(exclude_none=True) for segment in payload.request_segments]
    message = message_repo.insert(
        {
            "user_id": user_id,
            "session_id": session_id,
            "select_mode": payload.select_mode,
            "request_id": payload.request_id or uuid.uuid4().hex,
            "request_text": payload.request_text,
            "response_text": "",
            "request_segments": segments or None,
            "status": STATUS_GENERATING,
        }
    )

    # 上下文在用户消息落库后构建：查询只取 status=1，当前这条生成中的消息不会重复注入
    context = memory.build_context(session_id, payload.request_text)
    return StreamState(session=session, message=message, context=context, chain=chain)


def _sse(event: str, data: dict) -> str:
    """编码一条 SSE 消息；JSON 序列化保证正文中的换行不会破坏事件边界。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _persist_failed(message_id: int, text: str) -> None:
    """失败 / 中断时同步落库。

    取消场景下不能再 await（任务已被取消），因此用同步调用保住部分内容。
    """
    try:
        message_repo.update_result(message_id, text, STATUS_FAILED)
    except Exception:
        logger.exception("流式对话失败状态落库失败 | message_id=%s", message_id)


async def stream_reply(state: StreamState) -> AsyncIterator[str]:
    """生成 SSE 事件流；成功回写 status=1，失败 / 断开回写 status=2。"""
    message_id = state.message["id"]
    yield _sse(
        EVENT_META,
        {
            "session_id": state.session["id"],
            "message_id": message_id,
            "request_id": state.message["request_id"],
        },
    )

    chunks: list[str] = []
    persisted = False
    try:
        async for chunk in state.chain.astream(state.context):
            if not chunk:
                continue
            chunks.append(chunk)
            yield _sse(EVENT_DELTA, {"content": chunk})

        text = "".join(chunks)
        await run_in_threadpool(
            message_repo.update_result, message_id, text, STATUS_DONE
        )
        persisted = True
        yield _sse(EVENT_DONE, {"message_id": message_id, "status": STATUS_DONE})
    except asyncio.CancelledError:
        # 客户端断开：不吞异常，交给 finally 保留已生成内容并标记失败
        raise
    except Exception:
        logger.exception("流式对话生成失败 | message_id=%s", message_id)
        yield _sse(EVENT_ERROR, {"code": 502, "message": "AI 服务暂时不可用，请稍后重试"})
    finally:
        if not persisted:
            _persist_failed(message_id, "".join(chunks))
