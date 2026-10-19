"""业务层：用户业务规则（唯一性校验、密码哈希、字段组装）。

本层不关心 HTTP 细节，只做业务判断；错误统一抛 BusinessException，
由全局异常处理器转成标准错误响应体，路由层因此可以保持极薄。
"""

from fastapi import status

from ..core.exceptions import BusinessException
from ..core.security import hash_password
from ..db import user_repo as db
from ..schemas.user import UserCreate, UserUpdate


def _ensure_unique(username: str | None, exclude_id: int | None = None) -> None:
    """校验用户名唯一性；exclude_id 用于更新时排除自身。"""
    if username is not None:
        existed = db.find_by_username(username)
        if existed and existed["id"] != exclude_id:
            raise BusinessException(
                "用户名已被占用",
                http_status=status.HTTP_409_CONFLICT,
                detail=f"username={username}",
            )


def create_user(payload: UserCreate) -> dict:
    """创建用户：唯一性校验 → 密码哈希 → 落库（create_time 由数据库填充）。"""
    _ensure_unique(payload.username)
    record = {
        "username": payload.username,
        "password": hash_password(payload.password),  # 只存哈希，不保留明文
    }
    return db.insert(record)


def list_users() -> list[dict]:
    """查询用户列表。"""
    return db.list_all()


def get_user(user_id: int) -> dict:
    """按 id 查询用户，不存在则 404。"""
    user = db.get(user_id)
    if user is None:
        raise BusinessException(
            f"用户 {user_id} 不存在",
            http_status=status.HTTP_404_NOT_FOUND,
            detail=f"user_id={user_id}",
        )
    return user


def update_user(user_id: int, payload: UserUpdate) -> dict:
    """更新用户：只更新显式传入且非空的字段；若改密码则重新哈希。"""
    get_user(user_id)  # 先确保用户存在，不存在直接 404
    # exclude_unset：区分「未传」与「传了值」；exclude_none：显式传 null 视为不更新
    fields = payload.model_dump(exclude_unset=True, exclude_none=True)
    _ensure_unique(fields.get("username"), exclude_id=user_id)
    if "password" in fields:
        fields["password"] = hash_password(fields["password"])
    return db.update(user_id, fields)


def delete_user(user_id: int) -> None:
    """删除用户，不存在则 404。"""
    if not db.delete(user_id):
        raise BusinessException(
            f"用户 {user_id} 不存在",
            http_status=status.HTTP_404_NOT_FOUND,
            detail=f"user_id={user_id}",
        )
