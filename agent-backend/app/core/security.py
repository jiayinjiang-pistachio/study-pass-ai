"""安全能力：密码哈希（bcrypt）+ JWT 令牌（签发 / 校验），本模块是唯一入口。

- 密码：对外只暴露 hash_password / verify_password，业务层不感知算法，
  后续更换算法（如 argon2）只需改这里。
- 令牌：对外只暴露 create_access_token / create_refresh_token / decode_token，
  签名密钥从环境变量读取（见 app/core/config.py），禁止硬编码。
"""

from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext

from .config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    JWT_ALGORITHM,
    REFRESH_TOKEN_EXPIRE_DAYS,
    get_jwt_secret,
)
from .exceptions import BusinessException

# 使用 bcrypt 方案做单向哈希；deprecated="auto" 便于将来平滑升级算法
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    """生成密码哈希。盐值随机，同一明文每次结果都不同。"""
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """校验明文密码与哈希是否匹配（登录等场景使用）。"""
    return _pwd_context.verify(plain_password, hashed_password)


# ---- JWT 令牌 ----

# 令牌类型声明：区分访问令牌与刷新令牌，防止用刷新令牌直接访问受保护接口
ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"


def _encode(subject: int, token_type: str, expires_delta: timedelta) -> str:
    """签发一枚 JWT：sub（用户 id，规范要求字符串）、type、iat、exp。"""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(subject),
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


def create_access_token(subject: int, expires_delta: timedelta | None = None) -> str:
    """签发访问令牌（短有效期，用于访问受保护接口）。"""
    return _encode(
        subject,
        ACCESS_TOKEN_TYPE,
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def create_refresh_token(subject: int, expires_delta: timedelta | None = None) -> str:
    """签发刷新令牌（长有效期，仅用于换取新的访问令牌）。"""
    return _encode(
        subject,
        REFRESH_TOKEN_TYPE,
        expires_delta or timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    )


def decode_token(token: str, expected_type: str) -> dict:
    """解码并校验令牌，返回 payload。

    过期 / 签名非法 / 类型不符均抛 BusinessException(401)，由全局处理器统一转成
    错误信封；detail 只写原因，不回传密钥或令牌原文。
    """
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise BusinessException(
            "登录状态已过期", http_status=401, detail="token expired"
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise BusinessException(
            "凭证无效", http_status=401, detail="invalid token"
        ) from exc
    if payload.get("type") != expected_type:
        raise BusinessException(
            "凭证类型错误", http_status=401, detail=f"expected={expected_type}"
        )
    return payload

