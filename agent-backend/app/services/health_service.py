"""业务层：健康检查（服务存活 + 数据库连通性）。

数据库异常统一转成 SystemException（503），由全局异常处理器输出标准错误信封，
路由层因此无需 try/except。
"""

from fastapi import status

from ..core.exceptions import SystemException
from ..db import health_repo


def check() -> dict:
    """探活：数据库可连返回 ok，否则抛 SystemException(503)。"""
    try:
        health_repo.ping()
    except Exception as exc:  # 任何连接/查询异常都视为数据库不可用
        raise SystemException(
            "数据库连接异常",
            detail=str(exc),
            http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exc
    return {"status": "ok", "database": "up"}
