"""A2A（Agent-to-Agent）消息信封：统一工作流节点间的输出契约。"""

from typing import Any

from pydantic import BaseModel, Field


class A2AEnvelope(BaseModel):
    """节点间传递的最小信封；payload 必须是 JSON 可序列化的字典。"""

    from_agent: str = Field(..., description="产出该消息的智能体")
    payload_type: str = Field(..., description="载荷类型，如 weak_points")
    payload: dict[str, Any] = Field(default_factory=dict, description="业务载荷")
    next_agent: str | None = Field(
        None, description="建议的下一跳智能体；None 表示流程结束"
    )
    confidence: float = Field(
        1.0, ge=0.0, le=1.0, description="产出方对消息的置信度"
    )
