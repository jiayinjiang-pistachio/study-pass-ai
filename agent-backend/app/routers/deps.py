"""路由层共享依赖：从 Bearer 访问令牌解析当前登录用户。

放路由层而非 core，是因为它需要查用户（业务）；core 约定不依赖业务。
本模块只依赖 core + services，不直接碰 db（见 AGENTS.md §2.2）。
"""

from fastapi import Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..core.exceptions import BusinessException
from ..core.security import ACCESS_TOKEN_TYPE, decode_token
from ..services import auth_service

# auto_error=False：缺令牌时不抛框架 403，而是由本依赖统一抛 401 信封
_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    """校验访问令牌并返回当前用户；缺失 / 过期 / 非法 / 类型错一律 401。"""
    if credentials is None:
        raise BusinessException(
            "未提供认证凭证",
            http_status=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
        )
    payload = decode_token(credentials.credentials, expected_type=ACCESS_TOKEN_TYPE)
    return auth_service.resolve_user(int(payload["sub"]))
