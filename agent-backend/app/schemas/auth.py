"""校验层：鉴权相关的 Pydantic v2 模型。

- RegisterIn：注册入参，在 UserCreate 基础上叠加弱密码强度校验；
- LoginIn：登录入参（不套弱密码强度校验——那是注册约束）；
- TokenOut：登录 / 刷新出参（双令牌）；
- RefreshIn：刷新入参（携带刷新令牌）。

校验失败抛 ValueError，由全局处理器统一转成 422 信封，业务层无需重复判断。
"""

from pydantic import BaseModel, Field, model_validator

from .user import UserCreate

# 常见弱口令黑名单（统一按小写比对）
WEAK_PASSWORDS = {
    "123456",
    "12345678",
    "password",
    "passw0rd",
    "abc123",
    "111111",
    "qwerty",
    "admin123",
    "iloveyou",
}


class RegisterIn(UserCreate):
    """注册入参：复用 UserCreate 的长度约束，叠加弱密码强度校验。"""

    @model_validator(mode="after")
    def _check_strength(self) -> "RegisterIn":
        pwd, name = self.password, self.username
        if pwd.lower() in WEAK_PASSWORDS:
            raise ValueError("密码过于简单，请更换")
        if not any(c.isalpha() for c in pwd):
            raise ValueError("密码必须包含字母")
        if not any(c.isdigit() for c in pwd):
            raise ValueError("密码必须包含数字")
        if name.lower() in pwd.lower():
            raise ValueError("密码不能包含用户名")
        return self


class LoginIn(BaseModel):
    """登录入参：只做基本长度约束，强度校验是注册的事。"""

    username: str = Field(..., min_length=1, max_length=32, description="用户名")
    password: str = Field(..., min_length=1, max_length=72, description="明文密码")


class TokenOut(BaseModel):
    """令牌出参：登录 / 刷新统一返回双令牌。"""

    access_token: str = Field(..., description="访问令牌（访问受保护接口）")
    refresh_token: str = Field(..., description="刷新令牌（换取新的访问令牌）")
    token_type: str = Field("bearer", description="令牌类型，固定 bearer")


class RefreshIn(BaseModel):
    """刷新入参：携带登录时下发的刷新令牌。"""

    refresh_token: str = Field(..., min_length=1, description="刷新令牌")
