"""应用入口：创建 FastAPI 实例、配置日志、注册全局异常处理器与业务路由。

启动（默认端口与前端 Vite 代理一致）：
    uvicorn app.main:app --reload --port 8000
接口文档：http://127.0.0.1:8000/docs
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from .core import minio_client
from .core.config import UPLOAD_DIR, get_jwt_secret
from .core.handlers import register_exception_handlers
from .core.logging import setup_logging
from .routers import auth as auth_router
from .routers import file as file_router
from .routers import health as health_router
from .routers import interview as interview_router
from .routers import profile as profile_router
from .routers import prompt as prompt_router
from .routers import session as session_router
from .routers import user as user_router
from .services import prompt_template_service, resource_cleanup

logger = logging.getLogger(__name__)

# 先配置日志，保证后续（含异常处理器）的日志都走统一格式
setup_logging()

# 启动即校验 JWT 密钥已配置：缺失属于致命配置问题，宁可启动失败也不带病运行
get_jwt_secret()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """启动时预热提示词缓存、确保 MinIO 桶存在并拉起清理线程；关闭时停止线程。"""
    try:
        # 同步 DB / Redis 操作放到线程池，避免阻塞事件循环
        await run_in_threadpool(prompt_template_service.load_active_templates)
    except Exception:
        # Redis 不可用不阻断启动：提示词接口读取时会回源 MySQL
        logger.warning("提示词缓存预热失败，读取时将回源数据库", exc_info=True)

    try:
        minio_client.ensure_bucket()
    except Exception:
        # MinIO 不可用不阻断服务启动：上传接口会返回 503，其他接口不受影响
        logger.warning("MinIO 初始化失败，上传接口暂不可用", exc_info=True)

    resource_cleanup.start_cleanup_thread()
    yield
    resource_cleanup.stop_cleanup_thread()


app = FastAPI(
    title="学面通 AI · agent-backend",
    description="学习 / 面试 AI 助手后端服务（四层架构：路由 → 校验 → 业务 → 数据库）",
    version="0.1.0",
    lifespan=lifespan,
)

# 注册全局异常处理器：统一转成 {code, message, detail} 错误响应体
register_exception_handlers(app)

# 上传文件静态访问（头像等）：挂载前先建目录，避免首次启动因目录缺失失败
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# 按业务模块注册路由
app.include_router(user_router.router)
app.include_router(auth_router.router)
app.include_router(session_router.router)
app.include_router(interview_router.router)
app.include_router(file_router.router)
app.include_router(file_router.public_router)
app.include_router(profile_router.router)
app.include_router(prompt_router.router)
app.include_router(health_router.router)
