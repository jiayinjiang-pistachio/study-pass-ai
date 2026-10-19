"""应用入口：创建 FastAPI 实例、配置日志、注册全局异常处理器与业务路由。

启动（默认端口与前端 Vite 代理一致）：
    uvicorn app.main:app --reload --port 8000
接口文档：http://127.0.0.1:8000/docs
"""

from fastapi import FastAPI

from .core.handlers import register_exception_handlers
from .core.logging import setup_logging
from .routers import auth as auth_router
from .routers import health as health_router
from .routers import user as user_router

# 先配置日志，保证后续（含异常处理器）的日志都走统一格式
setup_logging()

app = FastAPI(
    title="学面通 AI · agent-backend",
    description="学习 / 面试 AI 助手后端服务（四层架构：路由 → 校验 → 业务 → 数据库）",
    version="0.1.0",
)

# 注册全局异常处理器：统一转成 {code, message, detail} 错误响应体
register_exception_handlers(app)

# 按业务模块注册路由
app.include_router(user_router.router)
app.include_router(auth_router.router)
app.include_router(health_router.router)
