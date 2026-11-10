"""路由层：总控聊天入口与能力下发。

`POST /api/agent/chat` 只返回 SSE：总控先完成路由规划，再按统一事件协议
（meta → agent → delta / task → done）输出，失败以 error 收尾。
会话校验与路由在建立流之前完成，404 / 429 仍是标准 JSON 错误信封。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from ..agent.registry import public_capabilities
from ..core.rate_limit import enforce_chat_limit
from ..schemas.agent import AgentCapabilityOut, AgentChatIn
from ..schemas.response import ResponseModel, ok
from ..services.orchestrator_service import OrchestratorService
from .deps import get_current_user

router = APIRouter(
    prefix="/api/agent",
    tags=["agent"],
    dependencies=[Depends(get_current_user)],
)


@router.post(
    "/chat",
    response_class=StreamingResponse,
    summary="总控聊天入口（SSE）",
    dependencies=[Depends(enforce_chat_limit)],
)
def agent_chat(
    payload: AgentChatIn,
    current_user: dict = Depends(get_current_user),
) -> StreamingResponse:
    """规划本轮能力并流式返回：普通聊天走 delta，任务走 task 事件。

    规划阶段同步执行（路由函数由 FastAPI 放入线程池），
    因此会话不存在、限流超限等错误仍返回标准 JSON 信封。
    """
    service = OrchestratorService()
    plan = service.plan(current_user["id"], payload)
    return StreamingResponse(
        service.stream(plan, current_user["id"], payload),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # 关闭 Nginx 等反向代理的缓冲，保证增量事件实时下发
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/capabilities",
    response_model=ResponseModel[list[AgentCapabilityOut]],
    summary="查询可用能力",
)
def list_capabilities(
    session_mode: Annotated[
        int | None,
        Query(ge=0, le=2, description="房间：0=学习室，1=面试间，2=笔记本；缺省返回全部"),
    ] = None,
) -> dict:
    """前端据此渲染快捷按钮；前置数据只返回标识，是否可用由聊天时段兜底。"""
    return ok(public_capabilities(session_mode))
