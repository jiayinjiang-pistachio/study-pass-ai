"""通用重试工具：只处理瞬时故障的重复执行，不感知任何业务。

设计约束：
- 只做重试与日志，不做状态持久化、不依赖数据库 / HTTP；
- 重试耗尽抛 `RetryExhaustedError`（携带节点、次数与原始异常），由业务层决定落库与对外错误；
- 默认首次执行 + 1 次重试，特殊节点可通过 `RetryPolicy` 调整次数或判定条件。
"""

import logging
from collections.abc import Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

DEFAULT_MAX_ATTEMPTS = 2
T = TypeVar("T")

__all__ = [
    "DEFAULT_MAX_ATTEMPTS",
    "RetryExhaustedError",
    "RetryPolicy",
    "run_with_retry",
]


class RetryExhaustedError(Exception):
    """重试耗尽：标准化错误节点、尝试次数与最后一次原始异常。"""

    def __init__(self, node: str, attempts: int, last_error: Exception) -> None:
        self.node = node
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(f"节点 {node} 重试 {attempts} 次仍失败：{last_error}")


class RetryPolicy:
    """可复用的重试策略；实例无状态，可安全跨请求共享。"""

    def __init__(
        self,
        *,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        retry_on: tuple[type[Exception], ...] = (Exception,),
        should_retry: Callable[[Exception], bool] | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts 必须 >= 1")
        self.max_attempts = max_attempts
        self.retry_on = retry_on
        self.should_retry = should_retry

    def run(self, action: Callable[[], T], *, node: str) -> T:
        """执行 action；命中重试条件时自动重试，耗尽抛 RetryExhaustedError。"""
        attempt = 1
        while True:
            try:
                return action()
            except self.retry_on as exc:
                # 自定义判定为「不可重试」时直接抛出原始异常，保留业务错误分类
                if self.should_retry is not None and not self.should_retry(exc):
                    raise
                if attempt >= self.max_attempts:
                    logger.error(
                        "节点执行重试耗尽 | node=%s attempts=%s error=%s",
                        node,
                        attempt,
                        exc,
                        exc_info=True,
                    )
                    raise RetryExhaustedError(node, attempt, exc) from exc
                logger.warning(
                    "节点执行失败，准备重试 | node=%s attempt=%s/%s error=%s",
                    node,
                    attempt,
                    self.max_attempts,
                    exc,
                )
                attempt += 1


def run_with_retry(
    action: Callable[[], T],
    *,
    node: str,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    retry_on: tuple[type[Exception], ...] = (Exception,),
    should_retry: Callable[[Exception], bool] | None = None,
) -> T:
    """按传入策略执行 action，是节点接入重试的便捷入口。"""
    return RetryPolicy(
        max_attempts=max_attempts,
        retry_on=retry_on,
        should_retry=should_retry,
    ).run(action, node=node)
