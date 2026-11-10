"""业务层：A2A 统一派发。

专家 Agent 只产出 `A2AEnvelope` 表达接力意图；本服务负责：
1. 解析信封并交给 dispatcher 做白名单 / 置信度 / next_agent 校验；
2. 校验链路跳数与自循环，超限的接力直接拒绝；
3. 按 next_agent 查找已注册的 handler；
4. handler 未实现时返回 pending，不阻塞上游流程；
5. 对已完成的派发按 (user_id, trace_id, next_agent) 做进程内幂等复用。

新增下游 Agent 只需调用 `register_handler` 登记，不修改派发逻辑。
"""

import logging
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

from ..agent.a2a import A2AEnvelope, decide_next_agent
from ..agent.a2a.rules import HANDOFF_RULES, MAX_HOPS, MIN_CONFIDENCE

logger = logging.getLogger(__name__)

STATUS_COMPLETED = "completed"
STATUS_PENDING = "pending"
STATUS_REJECTED = "rejected"
STATUS_FAILED = "failed"

# 幂等缓存只保留成功结果，且限制条数 / 时限，避免进程内存无限增长
IDEMPOTENT_TTL_SECONDS = 3600
IDEMPOTENT_MAX_ENTRIES = 256

HandoffHandler = Callable[[A2AEnvelope, dict[str, Any]], dict[str, Any]]

# next_agent -> handler；未注册的智能体一律返回 pending
HANDLERS: dict[str, HandoffHandler] = {}

_IDEMPOTENT_LOCK = threading.Lock()
_IDEMPOTENT_CACHE: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()


def register_handler(agent_name: str, handler: HandoffHandler) -> None:
    """登记下游智能体 handler；同名重复登记以最后一次为准。"""
    HANDLERS[agent_name] = handler


def _cache_key(context: dict[str, Any], trace_id: str, target: str) -> str | None:
    """缺少可信 user_id 时不做幂等，避免不同用户命中同一条链路。"""
    user_id = context.get("user_id")
    if not isinstance(user_id, int):
        return None
    return f"{user_id}:{trace_id}:{target}"


def _cache_get(key: str) -> dict[str, Any] | None:
    """命中未过期的已完成结果；过期项顺手清理。"""
    with _IDEMPOTENT_LOCK:
        entry = _IDEMPOTENT_CACHE.get(key)
        if entry is None:
            return None
        if time.time() - entry[0] > IDEMPOTENT_TTL_SECONDS:
            _IDEMPOTENT_CACHE.pop(key, None)
            return None
        _IDEMPOTENT_CACHE.move_to_end(key)
        return dict(entry[1])


def _cache_put(key: str, result: dict[str, Any]) -> None:
    """写入成功结果并淘汰最旧项。"""
    with _IDEMPOTENT_LOCK:
        _IDEMPOTENT_CACHE[key] = (time.time(), dict(result))
        _IDEMPOTENT_CACHE.move_to_end(key)
        while len(_IDEMPOTENT_CACHE) > IDEMPOTENT_MAX_ENTRIES:
            _IDEMPOTENT_CACHE.popitem(last=False)


def reset_idempotency_cache() -> None:
    """测试辅助：清空进程内幂等缓存。"""
    with _IDEMPOTENT_LOCK:
        _IDEMPOTENT_CACHE.clear()


def _result_ref(result: dict[str, Any] | None) -> str | None:
    """从下游产物提取引用 ID，没有可追溯产物时返回 None。"""
    if not isinstance(result, dict):
        return None
    for key in ("note_id", "run_id", "message_id"):
        value = result.get(key)
        if value is not None:
            return str(value)
    return None


class A2AHandoffService:
    """校验并派发 A2A 信封，自身不承载任何下游业务逻辑。"""

    def dispatch(
        self, envelope: dict[str, Any] | None, *, context: dict[str, Any]
    ) -> dict[str, Any]:
        """接收信封 → 校验 → 路由 handler；返回标准化派发结果。"""
        if not envelope:
            return self._result(STATUS_REJECTED, reason="缺少 A2A 信封")

        try:
            parsed = A2AEnvelope(**envelope)
        except Exception:
            logger.warning("A2A 信封解析失败", exc_info=True)
            return self._result(STATUS_REJECTED, reason="A2A 信封格式非法")

        trace_id = parsed.trace_id or uuid.uuid4().hex
        target = parsed.next_agent

        if target is not None and target == parsed.from_agent:
            logger.info(
                "A2A 自循环接力被拒绝 | agent=%s trace_id=%s",
                parsed.from_agent,
                trace_id,
            )
            return self._result(
                STATUS_REJECTED,
                from_agent=parsed.from_agent,
                next_agent=target,
                trace_id=trace_id,
                hops=parsed.hops,
                reason="禁止自循环接力",
            )

        if parsed.hops >= MAX_HOPS:
            logger.info(
                "A2A 接力跳数超限 | from=%s to=%s hops=%s trace_id=%s",
                parsed.from_agent,
                target,
                parsed.hops,
                trace_id,
            )
            return self._result(
                STATUS_REJECTED,
                from_agent=parsed.from_agent,
                next_agent=target,
                trace_id=trace_id,
                hops=parsed.hops,
                reason=f"接力跳数超过上限 {MAX_HOPS}",
            )

        target = decide_next_agent(
            parsed, rules=HANDOFF_RULES, min_confidence=MIN_CONFIDENCE
        )
        if target is None:
            logger.info("A2A 接力未放行 | from=%s", parsed.from_agent)
            return self._result(
                STATUS_REJECTED,
                from_agent=parsed.from_agent,
                trace_id=trace_id,
                hops=parsed.hops,
                reason="置信度不足或未命中接力白名单",
            )

        cache_key = _cache_key(context, trace_id, target)
        if cache_key is not None:
            cached = _cache_get(cache_key)
            if cached is not None:
                logger.info(
                    "A2A 幂等命中 | from=%s to=%s trace_id=%s",
                    parsed.from_agent,
                    target,
                    trace_id,
                )
                cached["idempotent"] = True
                return cached

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
                trace_id=trace_id,
                hops=parsed.hops,
                reason=f"{target} handler 未实现",
            )

        try:
            result = handler(parsed, context)
        except Exception:
            logger.error(
                "A2A handler 执行失败 | from=%s to=%s trace_id=%s",
                parsed.from_agent,
                target,
                trace_id,
                exc_info=True,
            )
            return self._result(
                STATUS_FAILED,
                from_agent=parsed.from_agent,
                next_agent=target,
                trace_id=trace_id,
                hops=parsed.hops,
                reason="下游 handler 执行失败",
            )

        completed = self._result(
            STATUS_COMPLETED,
            from_agent=parsed.from_agent,
            next_agent=target,
            trace_id=trace_id,
            hops=parsed.hops + 1,
            result_ref=_result_ref(result),
            result=result,
        )
        if cache_key is not None:
            _cache_put(cache_key, completed)

        logger.info(
            "A2A 接力已完成 | from=%s to=%s trace_id=%s hops=%s",
            parsed.from_agent,
            target,
            trace_id,
            completed["hops"],
        )
        return completed

    @staticmethod
    def _result(
        status: str,
        *,
        from_agent: str | None = None,
        next_agent: str | None = None,
        trace_id: str | None = None,
        hops: int = 0,
        result_ref: str | None = None,
        result: dict[str, Any] | None = None,
        reason: str | None = None,
        idempotent: bool = False,
    ) -> dict[str, Any]:
        """统一派发结果结构，便于前端与排查统一消费。"""
        return {
            "status": status,
            "from_agent": from_agent,
            "next_agent": next_agent,
            "trace_id": trace_id,
            "hops": hops,
            "result_ref": result_ref,
            "result": result,
            "reason": reason,
            "idempotent": idempotent,
        }
