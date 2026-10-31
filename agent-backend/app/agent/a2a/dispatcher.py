"""A2A 接力调度校验：只做纯校验，不内置任何业务规则。

白名单与置信度阈值由调用方注入，便于不同工作流复用同一套校验逻辑。
"""

import logging
from collections.abc import Iterable, Mapping

from .envelope import A2AEnvelope

logger = logging.getLogger(__name__)


def decide_next_agent(
    envelope: A2AEnvelope,
    *,
    rules: Mapping[str, Iterable[str]],
    min_confidence: float,
) -> str | None:
    """按注入的规则校验信封后返回允许的下一跳；未通过返回 None，不修改信封。"""
    if envelope.confidence < min_confidence:
        return None

    target = envelope.next_agent
    if target is None:
        return None

    if target not in rules.get(envelope.from_agent, ()):
        return None

    logger.info(
        "A2A 接力放行 | from=%s to=%s confidence=%s",
        envelope.from_agent,
        target,
        envelope.confidence,
    )
    return target
