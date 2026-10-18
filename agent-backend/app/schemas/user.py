"""校验层：用户相关的 Pydantic v2 模型。

命名约定：
- XxxCreate / XxxUpdate 为请求模型（入参）；
- XxxOut 为响应模型（出参），显式排除 password，杜绝密码外泄。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# bcrypt 只处理前 72 字节，故密码上限取 72，超长直接在校验层拦截
PASSWORD_MIN_LENGTH = 6
PASSWORD_MAX_LENGTH = 72


class UserBase(BaseModel):
    """用户公共字段（请求与响应共用）。"""

    username: str = Field(..., min_length=3, max_length=32, description="用户名")
    email: EmailStr = Field(..., description="邮箱")
    full_name: str | None = Field(None, max_length=64, description="昵称 / 姓名")


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
    email: EmailStr | None = None
    full_name: str | None = Field(None, max_length=64)
    password: str | None = Field(None, min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
    is_active: bool | None = None


class UserOut(UserBase):
    """用户响应模型。

    该模型用于返回用户的公开信息，不包含 password；即使业务层返回了 password，也会被 Pydantic 自动过滤掉。

    字段说明：
    - id: 用户唯一标识，类型为 int。使用 Field(...) 表示该字段为必填项，必须在响应中返回，否则校验会失败。
    - is_active: 用户是否启用，类型为 bool。Field(...) 表示该字段也必须提供，不能缺失。
    - created_at: 用户创建时间，类型为 datetime。Field(...) 表示该字段是必填字段，返回时必须包含有效时间值。

    说明：
    - `Field(...)` 中的 `...` 是 Pydantic 的常用写法，表示“该字段必须传值”。
    - 在这里，`...` 代表强制校验：若响应对象缺少这些字段，模型实例化时会抛出校验错误。
    - 因为该模型继承自 `UserBase`，其余通用字段会继续沿用父类定义，而本模型重点声明了返回时必须存在的核心字段。
    """
    """用户响应模型：不含 password，即使业务层返回了也会被自动剔除。"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="用户 ID")
    is_active: bool = Field(..., description="是否启用")
    created_at: datetime = Field(..., description="创建时间")
