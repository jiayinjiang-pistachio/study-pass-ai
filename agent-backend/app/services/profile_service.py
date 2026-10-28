"""业务层：用户背景资料 CRUD。

一人一份资料，接口只操作当前登录用户（user_id 来自令牌），不做跨用户读写。
错误统一抛 BusinessException，由全局异常处理器转成标准错误响应。
"""

from fastapi import status

from ..core.exceptions import BusinessException
from ..db import user_profile_repo as db
from ..schemas.profile import ProfileCreate, ProfileUpdate

# 长期记忆允许自动写入的字段：覆盖全部业务画像字段，对话中的最新表述优先。
# 白名单仍保留，防止抽取结果混入 user_id / created_at 等非业务字段。
LONG_TERM_FIELDS: set[str] = {
    "target_job",
    "years_experience",
    "target_level",
    "target_skills",
    "weak_topics",
    "learning_goal",
    "learning_style",
    "interview_focus",
    "long_term_summary",
}


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


def get_profile_dict(user_id: int) -> dict | None:
    """读取用户画像原始字典；不存在返回 None。

    与 `get_profile` 不同：这是给长期记忆内部使用的读取入口，不抛 404，
    也不经过接口出参裁剪，因此包含长期记忆字段。
    """
    return db.get_by_user_id(user_id)


def create_or_update(user_id: int, fields: dict) -> dict:
    """按 user_id 创建或局部更新画像，供长期记忆后台任务写入。

    只接受 `LONG_TERM_FIELDS` 中的字段，防止抽取结果写入无关列；
    岗位 / 年限 / 职级 / 技能 / 薄弱点与长期字段一样，以用户最新表述为准。
    """
    allowed = {
        key: value for key, value in fields.items() if key in LONG_TERM_FIELDS
    }
    return db.upsert(user_id, allowed)
