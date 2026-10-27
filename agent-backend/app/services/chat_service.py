"""业务层：流式 AI 对话（SSE）。

流程：校验会话归属 → 按需检索知识库 → 落库用户消息（status=0）→
记忆层构建上下文（命中资料时拼在本轮问题前）→ 提示词层组装链路 →
模型层流式输出 → 回写回复正文、状态与来源索引。

SSE 事件约定（每条 data 均为 JSON）：
- meta : {session_id, message_id, request_id}        流开始，告知落库后的消息 ID
- delta: {content}                                   增量文本
- done : {message_id, status, sources}               生成完成，sources 为本轮参考资料
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
from ..rag.context import format_retrieved_chunks, should_retrieve
from ..schemas.chat import StreamChatIn
from .ai import prompt_layer
from .memory_service import MemoryService

logger = logging.getLogger(__name__)

STATUS_GENERATING = 0
STATUS_DONE = 1
STATUS_FAILED = 2

# 单轮注入的知识片段数：过多会挤占上下文，3 条足以覆盖多数提问
RAG_TOP_K = 3

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
    sources: list[dict]
    reference_sources: list[dict]


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


def _build_chain(
    session_mode: int, select_mode: int, *, rag_enabled: bool = False
) -> Runnable:
    """组装链路；模型配置缺失属于系统问题，对外统一 503。"""
    try:
        return prompt_layer.build_chat_chain(
            session_mode, select_mode, rag_enabled=rag_enabled
        )
    except RuntimeError as exc:
        raise SystemException(
            "AI 服务未配置，请联系管理员",
            http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


def _retrieve(user_id: int, request_text: str) -> list[dict]:
    """按需检索当前用户的知识库；检索失败只降级为无资料，不阻断对话。"""
    if not should_retrieve(request_text):
        return []

    # 延迟导入：避免应用启动时加载 qdrant / dashscope 等重依赖
    from ..rag import retriever

    try:
        return retriever.search_similar_chunks(
            request_text, user_id, top_k=RAG_TOP_K
        )
    except Exception:
        logger.warning(
            "知识库检索失败，本轮不注入资料 | user_id=%s", user_id, exc_info=True
        )
        return []


def _to_source(chunk: dict) -> dict:
    """SSE 下发的完整来源；chunk_id 即 Qdrant Point id / MySQL vector_id。"""
    return {
        "chunk_id": chunk["vector_id"],
        "resource_id": chunk["resource_id"],
        "chunk_index": chunk["chunk_index"],
        "file_name": chunk["file_name"],
        "score": chunk["score"],
        "text": chunk["text"],
    }


def _to_reference(chunk: dict) -> dict:
    """落库只保留定位字段与分数，原文留在 knowledge_chunks，避免重复存储。"""
    return {"chunk_id": chunk["vector_id"], "score": chunk["score"]}


def _build_input(request_text: str, retrieved: list[dict]) -> str:
    """命中资料时把参考文本拼到本轮问题前，作为模型的本轮上下文。"""
    rag_text = format_retrieved_chunks(retrieved)
    if not rag_text:
        return request_text
    return f"{rag_text}\n\n{request_text}"


def prepare_stream(
    user_id: int, session_id: int, payload: StreamChatIn
) -> StreamState:
    """校验会话与附件、落库用户消息、构建上下文。

    在返回 StreamingResponse 之前执行，因此 404 / 503 仍是标准 JSON 错误信封。
    """
    session = _get_owned_session(user_id, session_id)
    _ensure_segments_owned(user_id, payload)

    # 用原始问题做检索：确认 / 寒暄 / 推进语等无意义输入在这里被跳过
    retrieved = _retrieve(user_id, payload.request_text)
    chain = _build_chain(
        session["session_mode"],
        payload.select_mode,
        rag_enabled=bool(retrieved),
    )

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

    # 上下文在用户消息落库后构建：查询只取 status=1，当前这条生成中的消息不会重复注入；
    # 历史读取（最近 N 轮 + 字符预算）封装在 MemoryService，主流程不关心查询细节
    context = MemoryService().build_context(
        session_id, _build_input(payload.request_text, retrieved)
    )
    return StreamState(
        session=session,
        message=message,
        context=context,
        chain=chain,
        sources=[_to_source(chunk) for chunk in retrieved],
        reference_sources=[_to_reference(chunk) for chunk in retrieved],
    )


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
            message_repo.update_result,
            message_id,
            text,
            STATUS_DONE,
            state.reference_sources or None,
        )
        persisted = True
        yield _sse(
            EVENT_DONE,
            {
                "message_id": message_id,
                "status": STATUS_DONE,
                "sources": state.sources,
            },
        )
    except asyncio.CancelledError:
        # 客户端断开：不吞异常，交给 finally 保留已生成内容并标记失败
        raise
    except Exception:
        logger.exception("流式对话生成失败 | message_id=%s", message_id)
        yield _sse(EVENT_ERROR, {"code": 502, "message": "AI 服务暂时不可用，请稍后重试"})
    finally:
        if not persisted:
            _persist_failed(message_id, "".join(chunks))
