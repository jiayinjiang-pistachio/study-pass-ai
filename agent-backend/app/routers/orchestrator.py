"""路由层：流程总控入口。

同一接口按意图返回两种响应：工作流分支是 JSON 信封，聊天分支是 SSE。
因此不设置 response_class（否则 JSON 分支无法按 response_model 序列化），
SSE 契约通过 responses 参数在文档中声明。
"""

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from ..schemas.orchestrator import AgentTaskStartIn, AgentTaskWorkflowOut
from ..schemas.response import ResponseModel, ok
from ..services import chat_service
from ..services.orchestrator_service import OrchestratorService
from .deps import get_current_user

router = APIRouter(
    prefix="/api/agent",
    tags=["agent"],
    dependencies=[Depends(get_current_user)],
)


@router.post(
    "/tasks/start",
    response_model=ResponseModel[AgentTaskWorkflowOut],
    responses={
        200: {
            "content": {
                "text/event-stream": {"schema": {"type": "string"}},
            }
        }
    },
    summary="智能体任务总控入口（工作流 / 通用聊天）",
)
def start_agent_task(
    payload: AgentTaskStartIn,
    current_user: dict = Depends(get_current_user),
) -> StreamingResponse | dict:
    """关键词 / 语义命中出题意图 → 启动学习测评工作流（JSON）；否则流式聊天（SSE）。"""
    service = OrchestratorService()
    result = service.start_task(current_user["id"], payload)
    if result["route"] == "chat":
        state = chat_service.prepare_stream(
            current_user["id"],
            payload.session_id,
            service.build_chat_payload(payload),
        )
        # 与 /api/sessions/{id}/stream-chat 保持同一套 SSE 响应头
        return StreamingResponse(
            chat_service.stream_reply(state),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    return ok(result)
