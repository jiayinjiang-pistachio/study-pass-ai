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
from sqlalchemy import delete as sa_delete, select

from app.core import minio_client, rate_limit
from app.core.security import hash_password
from app.db import (
    interview_repo,
    message_repo,
    resource_repo,
    session_repo,
    user_repo,
)
from app.db.models import PromptTemplate
from app.db.session import SessionLocal
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


@pytest_asyncio.fixture
async def other_auth(
    client: httpx.AsyncClient, auth_user: dict
) -> tuple[dict, dict]:
    """造第二个测试用户并登录，返回 (user, headers)，用于越权隔离用例。"""
    name = f"{TEST_PREFIX}other_{uuid.uuid4().hex[:6]}"
    user = user_repo.insert(
        {"username": name, "password": hash_password(TEST_PASSWORD)}
    )
    resp = await client.post(
        "/api/auth/login",
        json={"username": name, "password": TEST_PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["data"]["access_token"]
    return user, {"Authorization": f"Bearer {token}"}


@pytest.fixture
def isolated_prompt_templates():
    """让提示词用例在空表下运行，结束后原样恢复（含 init_prompt 种子数据）。

    提示词模板是全局数据，而用例需要「作用域无生效版本 → 404」等干净前置状态；
    直接删除会破坏开发库中已初始化的数据，因此统一快照 + 还原。
    """
    with SessionLocal() as session:
        snapshot = [
            {column.name: getattr(row, column.name) for column in row.__table__.columns}
            for row in session.scalars(select(PromptTemplate)).all()
        ]
        session.execute(sa_delete(PromptTemplate))
        session.commit()

    yield

    with SessionLocal() as session:
        session.execute(sa_delete(PromptTemplate))
        for row in snapshot:
            session.add(PromptTemplate(**row))
        session.commit()

    try:
        from app.services import prompt_template_service

        prompt_template_service.load_active_templates()
    except Exception:
        # 缓存刷新失败不影响测试结论：读取会自动回源 MySQL
        pass


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
        # 会话级联数据先清：interviews 依赖 chat_messages.message_id
        for session in session_repo.list_all_for_user(user["id"]):
            interview_repo.delete_by_session(session["id"])
            message_repo.delete_by_session(session["id"])
            session_repo.delete(session["id"])
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
