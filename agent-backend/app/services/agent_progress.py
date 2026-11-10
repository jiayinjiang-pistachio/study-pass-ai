"""业务层：智能体执行节点进度上报。

能力在 worker 线程内同步执行，SSE 生成器在事件循环内运行；本模块只定义
上报协议与安全的上报函数，跨线程投递事件由总控（orchestrator_service）实现。

设计约束：进度只是可观测性，回调缺失或异常都不能影响业务主流程。
"""

import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)

STEP_START = "start"
STEP_DONE = "done"
STEP_FAILED = "failed"

# (node, title, status, detail, error)
StepCallback = Callable[[str, str, str, str | None, str | None], None]


def emit_step(
    on_step: StepCallback | None,
    node: str,
    title: str,
    status: str,
    *,
    detail: str | None = None,
    error: str | None = None,
) -> None:
    """向总控上报一个节点状态；任何异常都吞掉，不影响能力执行。"""
    if on_step is None:
        return
    try:
        on_step(node, title, status, detail, error)
    except Exception:
        logger.warning("智能体进度上报失败 | node=%s status=%s", node, status, exc_info=True)
