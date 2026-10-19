"""业务层：鉴权业务规则（登录校验、签发 / 刷新令牌、解析当前用户）。

本层不感知 HTTP；错误统一抛 BusinessException，由全局处理器转成标准响应体。
令牌的具体算法细节封装在 core/security.py，本层只做编排。
"""

from fastapi import status

from ..core.exceptions import BusinessException
from ..core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from ..db import user_repo


def authenticate(username: str, password: str) -> dict:
    """校验用户名 + 密码；失败统一 401，不暴露账号是否存在（防用户名枚举）。"""
    user = user_repo.find_by_username(username)
    if user is None or not verify_password(password, user["password"]):
        raise BusinessException(
            "用户名或密码错误",
            http_status=status.HTTP_401_UNAUTHORIZED,
            detail=f"username={username}",
        )
    return user


def issue_tokens(user_id: int) -> dict:
    """为指定用户签发一对令牌（访问 + 刷新）。"""
    return {
        "access_token": create_access_token(user_id),
        "refresh_token": create_refresh_token(user_id),
        "token_type": "bearer",
    }


def login(username: str, password: str) -> dict:
    """登录：校验凭证后签发双令牌。"""
    user = authenticate(username, password)
    return issue_tokens(user["id"])


def refresh(refresh_token: str) -> dict:
    """用刷新令牌换取新的双令牌：要求类型为 refresh 且用户仍存在。"""
    payload = decode_token(refresh_token, expected_type="refresh")
    user_id = int(payload["sub"])
    if user_repo.get(user_id) is None:
        raise BusinessException(
            "用户不存在",
            http_status=status.HTTP_401_UNAUTHORIZED,
            detail=f"user_id={user_id}",
        )
    return issue_tokens(user_id)


def resolve_user(user_id: int) -> dict:
    """按 id 取当前用户；不存在则 401（令牌有效但用户已删，视同未认证）。"""
    user = user_repo.get(user_id)
    if user is None:
        raise BusinessException(
            "用户不存在",
            http_status=status.HTTP_401_UNAUTHORIZED,
            detail=f"user_id={user_id}",
        )
    return user
