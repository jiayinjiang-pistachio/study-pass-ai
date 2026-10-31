"""业务配置：A2A 接力白名单与置信度阈值。

只放策略数据，不含执行逻辑；由业务层注入给调度器，保证调度器保持纯校验。
"""

MIN_CONFIDENCE = 0.6

# from_agent -> 允许接力到的下一跳；未登记的来源或目标一律不放行
HANDOFF_RULES: dict[str, tuple[str, ...]] = {
    "learning_evaluator": ("difficulty_learner", "note_archiver"),
}
