"""密码安全：统一封装 passlib 的 bcrypt 单向哈希。

对外只暴露 hash_password / verify_password，业务层不感知具体算法，
后续更换算法（如 argon2）只需改这里。
"""

from passlib.context import CryptContext

# 使用 bcrypt 方案做单向哈希；deprecated="auto" 便于将来平滑升级算法
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    """生成密码哈希。盐值随机，同一明文每次结果都不同。"""
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """校验明文密码与哈希是否匹配（登录等场景使用）。"""
    return _pwd_context.verify(plain_password, hashed_password)
