"""校验层：用户相关的 Pydantic v2 模型。

命名约定：
- XxxCreate / XxxUpdate 为请求模型（入参）；
- XxxOut 为响应模型（出参），显式排除 password，杜绝密码外泄。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# bcrypt 只处理前 72 字节，故密码上限取 72，超长直接在校验层拦截
PASSWORD_MIN_LENGTH = 6
PASSWORD_MAX_LENGTH = 72


class UserBase(BaseModel):
    """用户公共字段（请求与响应共用）。"""

    username: str = Field(..., min_length=3, max_length=32, description="用户名")


class UserCreate(UserBase):
    """创建用户入参。password 只在此处出现，落库前会被哈希。"""

    password: str = Field(
        ...,
        min_length=PASSWORD_MIN_LENGTH,
        max_length=PASSWORD_MAX_LENGTH,
        description="明文密码（仅入参，不落库）",
    )


class UserUpdate(BaseModel):
    """更新用户入参：字段全部可选，只更新显式传入的字段。"""

    username: str | None = Field(None, min_length=3, max_length=32)
    password: str | None = Field(None, min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)


class UserOut(UserBase):
    """用户响应模型：不含 password，即使业务层返回了也会被自动剔除。"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="用户 ID")
    avatar: str | None = Field(None, description="头像 URL（未上传时为 null）")
    create_time: datetime = Field(..., description="创建时间（由数据库自动填充）")
