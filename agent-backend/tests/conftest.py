"""冒烟测试夹具：进程内 ASGI 客户端 + 测试数据清理 + 鉴权辅助。

测试连的是 `.env` 里的真实 MySQL（需先 alembic upgrade head 建表）。
为避免污染，测试创建的用户统一带 TEST_PREFIX 前缀，每个用例结束后按前缀清理。
"""

import os
import uuid

# 在导入 app（进而导入 config）之前，为测试兜底一个 JWT 密钥：
# 这样即使本地 .env 未配置 JWT_SECRET，测试也能跑；真实环境仍要求显式配置。
os.environ.setdefault("JWT_SECRET", "test-only-secret")

import httpx
import pytest
import pytest_asyncio

from app.core import minio_client, rate_limit
from app.core.security import hash_password
from app.db import resource_repo, user_repo
from app.main import app

# 本轮测试运行唯一的前缀，用于精确清理测试期间创建的用户
TEST_PREFIX = f"smoke_{uuid.uuid4().hex[:6]}_"

# 测试用户统一密码（满足注册强度要求，也用于登录）
TEST_PASSWORD = "abc12345"


@pytest.fixture(autouse=True)
def reset_limiter() -> None:
    """每个用例前清空限流计数。

    ASGITransport 下所有请求来自同一 IP，若不重置，注册限流计数会跨用例累积，
    导致后续用例被误限流。
    """
    rate_limit.reset()


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


@pytest_asyncio.fixture
async def auth_user() -> dict:
    """造一个独立的「鉴权用」用户（与 username 夹具隔离，避免与被测用户重名）。

    直接经 user_repo 落库，绕过注册接口与其限流。
    """
    name = f"{TEST_PREFIX}auth_{uuid.uuid4().hex[:6]}"
    return user_repo.insert({"username": name, "password": hash_password(TEST_PASSWORD)})


@pytest_asyncio.fixture
async def auth_headers(client: httpx.AsyncClient, auth_user: dict) -> dict:
    """用 auth_user 登录，返回带 Bearer 访问令牌的请求头。"""
    resp = await client.post(
        "/api/auth/login",
        json={"username": auth_user["username"], "password": TEST_PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    access_token = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture(scope="session")
def minio_ready() -> None:
    """上传用例依赖真实 MinIO；不可用时跳过，不误报失败。"""
    try:
        minio_client.ensure_bucket()
    except Exception as exc:
        pytest.skip(f"MinIO 不可用，跳过上传用例：{exc}")


@pytest.fixture(autouse=True)
def cleanup_users() -> None:
    """每个用例结束后清理本轮测试创建的资源与用户；yield 保证失败也会执行。"""
    yield
    for user in user_repo.list_all():
        if not user["username"].startswith(TEST_PREFIX):
            continue
        for resource in resource_repo.list_by_user(user["id"]):
            try:
                key = (
                    minio_client.object_key_from_storage_path(resource["storage_path"])
                    if resource["storage_path"]
                    else None
                )
                if key:
                    minio_client.remove_object(key)
            except Exception:
                # 清理失败不影响测试结论，MinIO 对象可由过期任务兜底
                pass
        resource_repo.delete_by_user(user["id"])
        user_repo.delete(user["id"])
