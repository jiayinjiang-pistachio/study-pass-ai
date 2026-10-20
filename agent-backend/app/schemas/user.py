"""校验层：用户相关的 Pydantic v2 模型。

命名约定：
- XxxCreate / XxxUpdate 为请求模型（入参）；
- XxxOut 为响应模型（出参），显式排除 password，杜绝密码外泄。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    avatar: str | None = Field(None, description="头像访问地址（未上传时为 null）")
    create_time: datetime = Field(..., description="创建时间（由数据库自动填充）")

    @model_validator(mode="after")
    def _to_public_avatar_url(self) -> "UserOut":
        """库里存的是 minio:/... 路径，浏览器无法直接加载，统一转成公开读取地址。

        用文件名里的 MD5 作为 ?v= 版本号：头像更新后 URL 随之变化，避免命中旧缓存。
        """
        if self.avatar and self.avatar.startswith("minio:/"):
            version = self.avatar.rsplit("/", 1)[-1].split(".", 1)[0]
            self.avatar = f"/api/files/avatar/{self.id}?v={version}"
        return self
