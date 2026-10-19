"""校验层：鉴权相关的 Pydantic v2 模型。

注册入参在 UserCreate 基础上叠加弱密码强度校验；校验失败抛 ValueError，
由全局处理器统一转成 422 信封，业务层无需重复判断。
"""

from pydantic import model_validator

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
