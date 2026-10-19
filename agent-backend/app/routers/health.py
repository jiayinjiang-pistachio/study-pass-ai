"""路由层：健康检查（存活 + 数据库连通性）。

路径为 `/health`（运维探活端点），**有意不挂 /api 前缀**，与业务接口区分。
数据库不可用时由 service 抛 SystemException(503)，全局处理器输出错误信封。
"""

from fastapi import APIRouter

from ..schemas.health import HealthOut
from ..schemas.response import ResponseModel, ok
from ..services import health_service

router = APIRouter(tags=["system"])


@router.get("/health", response_model=ResponseModel[HealthOut], summary="健康检查（存活 + 数据库连通性）")
def health() -> dict:
    """校验服务存活与数据库连通性；数据库异常返回 503。"""
    return ok(health_service.check())
