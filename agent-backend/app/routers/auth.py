"""路由层：鉴权接口（注册）。

统一前缀 /api/auth。路由只做参数透传与状态码声明：限流走依赖、
弱密码校验走校验层、建用户复用 user_service，返回统一成功信封。
"""

from fastapi import APIRouter, Depends, status

from ..core.rate_limit import enforce_register_limit
from ..schemas.auth import RegisterIn
from ..schemas.response import ResponseModel, ok
from ..schemas.user import UserOut
from ..services import user_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=ResponseModel[UserOut],
    status_code=status.HTTP_200_OK,
    summary="用户注册",
    dependencies=[Depends(enforce_register_limit)],
)
def register(payload: RegisterIn) -> dict:
    """注册新用户：限流 → 弱密码校验（校验层）→ 唯一性校验 + bcrypt 哈希（业务层）。"""
    return ok(user_service.create_user(payload))
