"""校验层：用户背景资料（user_profiles）的 Pydantic v2 模型。

字段长度与提示词注入的清洗上限保持一致，避免入库值在注入时被意外截断。
"""

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

# 单个技能 / 薄弱点：最长 50 字（与 prompt_injection_service.ITEM_MAX_CHARS 对齐）
ProfileItem = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)
]


class ProfileBase(BaseModel):
    """背景资料公共字段：均可选，创建与更新共用。"""

    target_job: str | None = Field(None, max_length=64, description="目标岗位")
    years_experience: int | None = Field(None, ge=0, le=60, description="工作年限")
    target_level: str | None = Field(None, max_length=32, description="目标职级")
    target_skills: list[ProfileItem] | None = Field(
        None, max_length=20, description="已掌握技能"
    )
    weak_topics: list[ProfileItem] | None = Field(
        None, max_length=20, description="薄弱点"
    )


class ProfileCreate(ProfileBase):
    """创建背景资料入参（一人一行）。"""


class ProfileUpdate(ProfileBase):
    """更新背景资料入参：只更新显式传入且非空的字段。"""


class ProfileOut(ProfileBase):
    """背景资料出参（不暴露 user_id，接口只操作当前登录用户）。"""

    id: int
    created_at: int
