"""A2A 消息契约与接力调度。"""

from .dispatcher import decide_next_agent
from .envelope import A2AEnvelope

__all__ = ["A2AEnvelope", "decide_next_agent"]
