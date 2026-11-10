"""校验层：总控聊天入口与能力下发的请求 / 响应模型。

总控接口只返回 SSE，不使用统一 JSON 信封；因此这里仅约束入参与
能力列表出参，task 事件载荷由业务层按能力类型组装。
"""

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from .chat import SegmentIn
from .learning_workflow import (
    DEFAULT_QUESTION_COUNT,
    MAX_QUESTION_COUNT,
    ProviderName,
    RequestText,
)

AgentName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
]


class AgentChatIn(BaseModel):
    """总控聊天入参：一句自然语言 + 可选的快捷指令提示。"""

    session_id: int = Field(..., ge=1, description="所属会话 ID")
    request_text: RequestText = Field(..., description="用户问题 / 任务描述")
    preferred_agent: AgentName | None = Field(
        None,
        description="快捷按钮提示（一次性）；命中房间能力时优先，否则由总控自行判断",
    )
    select_mode: int = Field(
        0,
        ge=0,
        le=5,
        description="聊天子模式：0=默认，1=知识精讲，2=刷题，3=简历优化，4=模拟面试，5=面试复盘",
    )
    question_count: int | None = Field(
        None,
        ge=1,
        le=MAX_QUESTION_COUNT,
        description=(
            f"题目数量，1..{MAX_QUESTION_COUNT}；仅出题能力使用。"
            f"缺省时从 request_text 提取，仍无则 {DEFAULT_QUESTION_COUNT}"
        ),
    )
    provider: ProviderName | None = Field(
        None, description="模型服务商标识；仅出题能力记录使用"
    )
    request_id: str | None = Field(
        None, max_length=64, description="前端请求标识；聊天能力落库时使用"
    )
    request_segments: list[SegmentIn] = Field(
        default_factory=list, description="附件段；聊天能力落库时使用"
    )


class AgentCapabilityOut(BaseModel):
    """能力下发出参：前端据此渲染快捷按钮与能力说明。"""

    name: str = Field(..., description="能力标识")
    title: str = Field(..., description="展示名称")
    kind: str = Field(..., description="执行方式：chat / workflow / task")
    requires: list[str] = Field(..., description="前置数据标识")
    returns: str = Field(..., description="task 事件的产物类型")
    description: str = Field(..., description="一句话能力说明")
