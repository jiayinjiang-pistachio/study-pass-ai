"""冒烟测试夹具：进程内 ASGI 客户端 + 测试数据清理。

测试连的是 `.env` 里的真实 MySQL（需先 alembic upgrade head 建表）。
为避免污染，测试创建的用户统一带 TEST_PREFIX 前缀，每个用例结束后按前缀清理。
"""

import uuid

import httpx
import pytest
import pytest_asyncio

from app.db import user_repo
from app.main import app

# 本轮测试运行唯一的前缀，用于精确清理测试期间创建的用户
TEST_PREFIX = f"smoke_{uuid.uuid4().hex[:6]}_"


@pytest_asyncio.fixture
async def client() -> httpx.AsyncClient:
    """进程内驱动 FastAPI 的异步客户端，无需另起 uvicorn。"""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def username() -> str:
    """返回一个带测试前缀的唯一用户名。"""
    return f"{TEST_PREFIX}{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def cleanup_users() -> None:
    """每个用例结束后清理本轮测试创建的用户；yield 保证失败也会执行。"""
    yield
    for user in user_repo.list_all():
        if user["username"].startswith(TEST_PREFIX):
            user_repo.delete(user["id"])
