"""A2A（Agent-to-Agent）消息信封：统一工作流节点间的输出契约。"""

from typing import Any

from pydantic import BaseModel, Field


class A2AEnvelope(BaseModel):
    """节点间传递的最小信封；payload 必须是 JSON 可序列化的字典。

    trace_id / hops 用于串起同一条接力的完整链路并限制跳数，
    缺省时由派发服务补齐，下游产出新信封时应沿用上游 trace_id 并递增 hops。
    """

    from_agent: str = Field(..., description="产出该消息的智能体")
    payload_type: str = Field(..., description="载荷类型，如 weak_points")
    payload: dict[str, Any] = Field(default_factory=dict, description="业务载荷")
    next_agent: str | None = Field(
        None, description="建议的下一跳智能体；None 表示流程结束"
    )
    confidence: float = Field(
        1.0, ge=0.0, le=1.0, description="产出方对消息的置信度"
    )
    trace_id: str | None = Field(
        None, description="链路追踪 ID，缺省时由派发服务生成"
    )
    intent: str | None = Field(None, description="接力意图，便于审计与排查")
    hops: int = Field(0, ge=0, description="当前信封已经经过的接力跳数")
    result_ref: str | None = Field(
        None, description="上游产物的引用 ID（如 note_id），供链路追溯"
    )
    alternatives: list[str] = Field(
        default_factory=list, description="规划器考虑过的备选下一跳"
    )
