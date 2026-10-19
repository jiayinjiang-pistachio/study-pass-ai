"""通用能力：进程内固定窗口限流（IP 维度）。

以 FastAPI 依赖形式挂在需要限流的路由上；超限抛 BusinessException(429)，
交由全局处理器转成统一错误信封，路由层不写 try/except。

注意：计数存在进程内存，仅单机有效；多实例部署需换成 Redis 等共享存储。
"""

import threading
import time

from fastapi import Request, status

from .exceptions import BusinessException

WINDOW_SECONDS = 60
MAX_REQUESTS = 5

_lock = threading.Lock()
_buckets: dict[str, tuple[float, int]] = {}  # ip -> (window_start, count)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def enforce_register_limit(request: Request) -> None:
    """固定窗口限流：同一 IP 每 WINDOW_SECONDS 秒最多 MAX_REQUESTS 次。"""
    ip = _client_ip(request)
    now = time.monotonic()
    with _lock:
        start, count = _buckets.get(ip, (now, 0))
        if now - start >= WINDOW_SECONDS:  # 窗口过期 → 重置
            start, count = now, 0
        count += 1
        _buckets[ip] = (start, count)
        if count > MAX_REQUESTS:
            raise BusinessException(
                "注册过于频繁，请稍后再试",
                http_status=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"ip={ip}",
            )


def reset() -> None:
    """清空计数（仅供测试隔离使用）。"""
    with _lock:
        _buckets.clear()
