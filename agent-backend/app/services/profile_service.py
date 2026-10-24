"""业务层：用户背景资料 CRUD。

一人一份资料，接口只操作当前登录用户（user_id 来自令牌），不做跨用户读写。
错误统一抛 BusinessException，由全局异常处理器转成标准错误响应。
"""

from fastapi import status

from ..core.exceptions import BusinessException
from ..db import user_profile_repo as db
from ..schemas.profile import ProfileCreate, ProfileUpdate


def _not_found(user_id: int) -> BusinessException:
    """统一的「资料不存在」错误。"""
    return BusinessException(
        "用户背景资料不存在",
        http_status=status.HTTP_404_NOT_FOUND,
        detail=f"user_id={user_id}",
    )


def create_profile(user_id: int, payload: ProfileCreate) -> dict:
    """创建背景资料；同一用户已存在时返回 409。"""
    if db.get_by_user_id(user_id) is not None:
        raise BusinessException(
            "用户背景资料已存在",
            http_status=status.HTTP_409_CONFLICT,
            detail=f"user_id={user_id}",
        )
    return db.insert(user_id, payload.model_dump())


def get_profile(user_id: int) -> dict:
    """查询当前用户背景资料，不存在则 404。"""
    profile = db.get_by_user_id(user_id)
    if profile is None:
        raise _not_found(user_id)
    return profile


def update_profile(user_id: int, payload: ProfileUpdate) -> dict:
    """局部更新背景资料：只更新显式传入且非空的字段；不存在则 404。"""
    get_profile(user_id)  # 先确保存在，不存在直接 404
    fields = payload.model_dump(exclude_unset=True, exclude_none=True)
    updated = db.update(user_id, fields)
    if updated is None:
        raise _not_found(user_id)
    return updated


def delete_profile(user_id: int) -> None:
    """删除背景资料，不存在则 404。"""
    if not db.delete(user_id):
        raise _not_found(user_id)
