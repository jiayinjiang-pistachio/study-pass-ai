"""路由层：会话与聊天消息接口。

统一前缀 /api/sessions，整组需登录；所有查询按令牌中的 user_id 隔离数据。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from ..schemas.chat import StreamChatIn
from ..schemas.message import MessageListOut
from ..schemas.response import ResponseModel, ok
from ..schemas.session import SessionCreate, SessionListOut, SessionOut, SessionUpdate
from ..services import chat_service, message_service, session_service
from .deps import get_current_user

router = APIRouter(
    prefix="/api/sessions",
    tags=["sessions"],
    dependencies=[Depends(get_current_user)],
)

PageQuery = Annotated[int, Query(ge=1, description="页码，从 1 开始")]
PageSizeQuery = Annotated[int, Query(ge=1, le=100, description="每页条数，最大 100")]
SessionModeQuery = Annotated[
    int | None,
    Query(ge=0, le=2, description="按会话模式过滤：0=学习，1=面试，2=笔记；不传返回全部"),
]


@router.get(
    "",
    response_model=ResponseModel[SessionListOut],
    summary="分页查询当前用户的会话",
)
def list_sessions(
    page: PageQuery = 1,
    page_size: PageSizeQuery = 20,
    session_mode: SessionModeQuery = None,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """按创建时间倒序返回会话，支持按会话模式过滤。"""
    return ok(
        session_service.list_sessions(
            current_user["id"], page, page_size, session_mode
        )
    )


@router.post(
    "",
    response_model=ResponseModel[SessionOut],
    status_code=status.HTTP_200_OK,
    summary="创建会话",
)
def create_session(
    payload: SessionCreate,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """创建会话：标题 + 会话模式（0=学习，1=面试，2=笔记）。"""
    return ok(session_service.create_session(current_user["id"], payload))


@router.put(
    "/{session_id}",
    response_model=ResponseModel[SessionOut],
    summary="编辑会话标题",
)
def update_session(
    session_id: int,
    payload: SessionUpdate,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """只能修改自己的会话；不存在或不属于当前用户返回 404。"""
    return ok(session_service.update_session(current_user["id"], session_id, payload))


@router.delete(
    "/{session_id}",
    response_model=ResponseModel[None],
    summary="删除会话（级联清理消息、面试与附件资源）",
)
def delete_session(
    session_id: int,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """级联删除会话、消息、面试记录，以及消息附件引用的资源和 MinIO 对象。"""
    session_service.delete_session(current_user["id"], session_id)
    return ok(None)


@router.post(
    "/{session_id}/stream-chat",
    response_class=StreamingResponse,
    summary="流式对话（SSE）",
)
async def stream_chat(
    session_id: int,
    payload: StreamChatIn,
    current_user: dict = Depends(get_current_user),
) -> StreamingResponse:
    """一问一答的流式生成，返回 text/event-stream。

    事件依次为 meta → delta* → done；生成失败时以 error 收尾。
    会话不存在、附件越权在建立流之前返回标准错误信封。
    """
    state = await run_in_threadpool(
        chat_service.prepare_stream, current_user["id"], session_id, payload
    )
    return StreamingResponse(
        chat_service.stream_reply(state),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # 关闭 Nginx 等反向代理的缓冲，保证增量事件实时下发
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/{session_id}/messages",
    response_model=ResponseModel[MessageListOut],
    summary="分页查询会话聊天消息",
)
def list_messages(
    session_id: int,
    page: PageQuery = 1,
    page_size: PageSizeQuery = 20,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """返回正文、附件段、消息状态与关联面试 ID，按时间正序分页。"""
    return ok(
        message_service.list_messages(
            current_user["id"], session_id, page, page_size
        )
    )
