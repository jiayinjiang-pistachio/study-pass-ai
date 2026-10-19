"""路由层：鉴权接口（注册 / 登录 / 刷新令牌 / 当前用户）。

统一前缀 /api/auth。路由只做参数透传与状态码声明：限流走依赖、
弱密码校验走校验层、登录与令牌编排复用 auth_service，返回统一成功信封。
"""

from fastapi import APIRouter, Depends, status

from ..core.rate_limit import enforce_register_limit
from ..schemas.auth import LoginIn, RefreshIn, RegisterIn, TokenOut
from ..schemas.response import ResponseModel, ok
from ..schemas.user import UserOut
from ..services import auth_service, user_service
from .deps import get_current_user

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


@router.post(
    "/login",
    response_model=ResponseModel[TokenOut],
    status_code=status.HTTP_200_OK,
    summary="用户登录",
)
def login(payload: LoginIn) -> dict:
    """登录：校验用户名 + 密码，成功签发访问令牌与刷新令牌。"""
    return ok(auth_service.login(payload.username, payload.password))


@router.post(
    "/refresh",
    response_model=ResponseModel[TokenOut],
    status_code=status.HTTP_200_OK,
    summary="刷新访问令牌",
)
def refresh(payload: RefreshIn) -> dict:
    """用刷新令牌换取新的访问令牌（访问令牌过期时由前端调用后重试原请求）。"""
    return ok(auth_service.refresh(payload.refresh_token))


@router.get(
    "/me",
    response_model=ResponseModel[UserOut],
    summary="当前登录用户",
)
def me(current_user: dict = Depends(get_current_user)) -> dict:
    """返回当前令牌对应的用户信息（不含密码）。"""
    return ok(current_user)
