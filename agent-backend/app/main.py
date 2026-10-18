"""应用入口：创建 FastAPI 实例并挂载各业务路由。

启动（默认端口与前端 Vite 代理一致）：
    uvicorn app.main:app --reload --port 8000
接口文档：http://127.0.0.1:8000/docs
"""

from fastapi import FastAPI

from .routers import user as user_router

app = FastAPI(
    title="学面通 AI · agent-backend",
    description="学习 / 面试 AI 助手后端服务（四层架构：路由 → 校验 → 业务 → 数据库）",
    version="0.1.0",
)

# 按业务模块注册路由
app.include_router(user_router.router)


@app.get("/api/health", tags=["system"], summary="健康检查")
def health() -> dict[str, str]:
    """供前端 / 运维探活使用。"""
    return {"status": "ok"}
