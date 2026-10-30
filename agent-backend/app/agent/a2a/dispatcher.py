"""A2A 接力调度校验：只放行置信度达标且命中白名单的下一跳。"""

import logging

from .envelope import A2AEnvelope

logger = logging.getLogger(__name__)

MIN_CONFIDENCE = 0.6

# from_agent -> 允许接力到的下一跳；未登记的来源或目标一律不放行
HANDOFF_RULES: dict[str, tuple[str, ...]] = {
    "learning_evaluator": ("difficulty_learner", "note_archiver"),
}


def decide_next_agent(envelope: A2AEnvelope) -> str | None:
    """校验信封后返回允许的下一跳；未通过返回 None，不修改信封本身。"""
    if envelope.confidence < MIN_CONFIDENCE:
        return None

    target = envelope.next_agent
    if target is None:
        return None

    if target not in HANDOFF_RULES.get(envelope.from_agent, ()):
        return None

    logger.info(
        "A2A 接力放行 | from=%s to=%s confidence=%s",
        envelope.from_agent,
        target,
        envelope.confidence,
    )
    return target
