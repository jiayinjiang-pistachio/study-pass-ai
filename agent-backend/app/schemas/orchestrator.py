"""校验层：流程总控入口的请求 / 响应模型。

总控接口是「同接口 JSON / SSE 混合」的第二个例外：工作流分支返回统一信封，
聊天分支返回 text/event-stream，因此出参模型只描述工作流分支。
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from .chat import SegmentIn
from .learning_workflow import (
    DEFAULT_QUESTION_COUNT,
    MAX_QUESTION_COUNT,
    LearningWorkflowStartOut,
    ProviderName,
    RequestText,
)

AgentName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
]


class AgentTaskStartIn(BaseModel):
    """总控入口入参：agent_name 决定走工作流还是通用聊天。"""

    agent_name: AgentName = Field(..., description="智能体 / 工作流标识")
    session_id: int = Field(..., ge=1, description="所属会话 ID")
    request_text: RequestText = Field(..., description="用户问题 / 任务描述")
    select_mode: int = Field(
        0,
        ge=0,
        le=5,
        description="聊天子模式；工作流分支忽略，聊天分支透传",
    )
    question_count: int = Field(
        DEFAULT_QUESTION_COUNT,
        ge=1,
        le=MAX_QUESTION_COUNT,
        description=f"题目数量，1..{MAX_QUESTION_COUNT}；仅工作流分支使用",
    )
    provider: ProviderName | None = Field(
        None, description="模型服务商标识；仅工作流分支使用"
    )
    request_id: str | None = Field(
        None, max_length=64, description="前端请求标识；仅聊天分支使用"
    )
    request_segments: list[SegmentIn] = Field(
        default_factory=list, description="附件段；仅聊天分支使用"
    )


class AgentTaskWorkflowOut(LearningWorkflowStartOut):
    """工作流分支出参：在学习测评结果上追加路由元信息。"""

    route: Literal["workflow"] = Field("workflow", description="固定为 workflow")
    agent_name: str = Field(..., description="命中的智能体标识")
    workflow_type: str = Field(..., description="实际启动的工作流类型")
