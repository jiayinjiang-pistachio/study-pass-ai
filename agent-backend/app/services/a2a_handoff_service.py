"""业务层：A2A 统一派发。

专家 Agent 只产出 `A2AEnvelope` 表达接力意图；本服务负责：
1. 解析信封并交给 dispatcher 做白名单 / 置信度 / next_agent 校验；
2. 按 next_agent 查找已注册的 handler；
3. handler 未实现时返回 pending，不阻塞上游流程。

新增下游 Agent 只需调用 `register_handler` 登记，不修改派发逻辑。
"""

import logging
from collections.abc import Callable
from typing import Any

from ..agent.a2a import A2AEnvelope, decide_next_agent
from ..agent.a2a.rules import HANDOFF_RULES, MIN_CONFIDENCE

logger = logging.getLogger(__name__)

STATUS_COMPLETED = "completed"
STATUS_PENDING = "pending"
STATUS_REJECTED = "rejected"
STATUS_FAILED = "failed"

HandoffHandler = Callable[[A2AEnvelope, dict[str, Any]], dict[str, Any]]

# next_agent -> handler；未注册的智能体一律返回 pending
HANDLERS: dict[str, HandoffHandler] = {}


def register_handler(agent_name: str, handler: HandoffHandler) -> None:
    """登记下游智能体 handler；同名重复登记以最后一次为准。"""
    HANDLERS[agent_name] = handler


class A2AHandoffService:
    """校验并派发 A2A 信封，自身不承载任何下游业务逻辑。"""

    def dispatch(
        self, envelope: dict[str, Any] | None, *, context: dict[str, Any]
    ) -> dict[str, Any]:
        """接收信封 → 校验 → 路由 handler；返回标准化派发结果。"""
        if not envelope:
            return self._result(
                STATUS_REJECTED, reason="缺少 A2A 信封"
            )

        try:
            parsed = A2AEnvelope(**envelope)
        except Exception:
            logger.warning("A2A 信封解析失败", exc_info=True)
            return self._result(STATUS_REJECTED, reason="A2A 信封格式非法")

        target = decide_next_agent(
            parsed, rules=HANDOFF_RULES, min_confidence=MIN_CONFIDENCE
        )
        if target is None:
            logger.info("A2A 接力未放行 | from=%s", parsed.from_agent)
            return self._result(
                STATUS_REJECTED,
                from_agent=parsed.from_agent,
                reason="置信度不足或未命中接力白名单",
            )

        handler = HANDLERS.get(target)
        if handler is None:
            logger.info(
                "A2A 下游 handler 未实现 | from=%s to=%s",
                parsed.from_agent,
                target,
            )
            return self._result(
                STATUS_PENDING,
                from_agent=parsed.from_agent,
                next_agent=target,
                reason=f"{target} handler 未实现",
            )

        try:
            result = handler(parsed, context)
        except Exception:
            logger.error(
                "A2A handler 执行失败 | from=%s to=%s",
                parsed.from_agent,
                target,
                exc_info=True,
            )
            return self._result(
                STATUS_FAILED,
                from_agent=parsed.from_agent,
                next_agent=target,
                reason="下游 handler 执行失败",
            )

        logger.info(
            "A2A 接力已完成 | from=%s to=%s", parsed.from_agent, target
        )
        return self._result(
            STATUS_COMPLETED,
            from_agent=parsed.from_agent,
            next_agent=target,
            result=result,
        )

    @staticmethod
    def _result(
        status: str,
        *,
        from_agent: str | None = None,
        next_agent: str | None = None,
        result: dict[str, Any] | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """统一派发结果结构，便于前端与排查统一消费。"""
        return {
            "status": status,
            "from_agent": from_agent,
            "next_agent": next_agent,
            "result": result,
            "reason": reason,
        }
