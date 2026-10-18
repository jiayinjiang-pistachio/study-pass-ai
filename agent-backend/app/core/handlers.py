"""全局异常处理器：把各类异常统一转成 {code, message, detail} 响应体。

覆盖四类来源：
- BusinessException / SystemException：自定义业务 / 系统异常；
- RequestValidationError：Pydantic 参数校验失败（422）；
- StarletteHTTPException：框架抛出的 HTTP 异常（如 404 路由不存在）；
- Exception：兜底，避免内部细节外泄（500）。

日志级别：业务 / 参数错误记 WARNING，系统 / 未捕获错误记 ERROR（含堆栈）。
"""

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..schemas.response import ErrorResponse
from .exceptions import BusinessException, SystemException

logger = logging.getLogger(__name__)


def _error_json(http_status: int, message: str, detail: str | None = None) -> JSONResponse:
    """按统一错误信封构造 JSON 响应，body.code 与 HTTP 状态码保持一致。"""
    body = ErrorResponse(code=http_status, message=message, detail=detail)
    return JSONResponse(status_code=http_status, content=body.model_dump())


def register_exception_handlers(app: FastAPI) -> None:
    """注册全部全局异常处理器，应用启动时调用一次。"""

    @app.exception_handler(BusinessException)
    async def _handle_business(request: Request, exc: BusinessException) -> JSONResponse:
        logger.warning("业务错误 | %s %s | %s", request.method, request.url.path, exc.message)
        return _error_json(exc.http_status, exc.message, exc.detail)

    @app.exception_handler(SystemException)
    async def _handle_system(request: Request, exc: SystemException) -> JSONResponse:
        # 系统错误对外只给通用文案，真实原因（detail）记入日志供定位
        logger.error(
            "系统错误 | %s %s | %s",
            request.method,
            request.url.path,
            exc.detail or exc.message,
            exc_info=True,
        )
        return _error_json(exc.http_status, exc.message, exc.detail)

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        first = errors[0] if errors else {}
        # loc 形如 ("body", "email")，去掉 body 前缀后拼成 "email"
        loc = ".".join(str(p) for p in first.get("loc", ()) if p != "body")
        msg = first.get("msg", "参数校验失败")
        detail = f"{loc}: {msg}" if loc else msg
        logger.warning("参数校验失败 | %s %s | %s", request.method, request.url.path, detail)
        return _error_json(status.HTTP_422_UNPROCESSABLE_ENTITY, "请求参数不合法", detail)

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        logger.warning("HTTP 异常 | %s %s | %s", request.method, request.url.path, exc.detail)
        return _error_json(exc.status_code, str(exc.detail), None)

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, _exc: Exception) -> JSONResponse:
        # 兜底：不把内部异常细节返回给前端，只记日志
        logger.exception("未捕获异常 | %s %s", request.method, request.url.path)
        return _error_json(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "系统内部错误，请稍后重试", None
        )
