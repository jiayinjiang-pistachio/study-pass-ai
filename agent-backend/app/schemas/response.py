"""统一响应信封：所有接口（成功 / 失败）都返回同一结构。

- 成功：code=200，message="ok"，data 为业务数据；
- 失败：code 复用 HTTP 状态码（404 / 409 / 422 / 500），
  message 面向用户（中文），detail 面向开发者（定位用，可为 None）。
"""

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")

SUCCESS_CODE = 200
SUCCESS_MESSAGE = "ok"


class ResponseModel(BaseModel, Generic[T]):
    """统一成功响应信封。用作路由的 response_model，如 ResponseModel[UserOut]。"""

    code: int = Field(SUCCESS_CODE, description="状态码，200 表示成功")
    message: str = Field(SUCCESS_MESSAGE, description="提示信息")
    data: T | None = Field(None, description="业务数据")


class ErrorResponse(BaseModel):
    """统一错误响应信封（由全局异常处理器构造）。"""

    code: int = Field(..., description="错误码（复用 HTTP 状态码）")
    message: str = Field(..., description="面向用户的中文提示")
    detail: str | None = Field(None, description="面向开发者的定位信息")


def ok(data: T) -> dict[str, Any]:
    """构造成功响应体：{"code": 200, "message": "ok", "data": data}。"""
    return {"code": SUCCESS_CODE, "message": SUCCESS_MESSAGE, "data": data}
