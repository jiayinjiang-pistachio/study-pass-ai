"""注册接口冒烟测试：成功路径 + 弱密码拦截 + 重复用户名 + 限流。

运行：pytest tests/test_auth.py -v
依赖：本地 MySQL 已启动且执行过 alembic upgrade head。
"""

import httpx
import pytest

from app.core import rate_limit

VALID_PASSWORD = "abc12345"


@pytest.fixture(autouse=True)
def reset_limiter() -> None:
    """每个用例前清空限流计数。

    ASGITransport 下所有请求来自同一 IP，若不重置，计数会跨用例累积，
    导致后续用例被误限流。
    """
    rate_limit.reset()


async def _register(client: httpx.AsyncClient, username: str, password: str = VALID_PASSWORD) -> httpx.Response:
    return await client.post("/api/auth/register", json={"username": username, "password": password})


# ---- 成功路径 ----

async def test_register_ok(client: httpx.AsyncClient, username: str) -> None:
    """合法用户名 + 强密码注册返回 200，含 id/create_time，且不含密码。"""
    resp = await _register(client, username)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["username"] == username
    assert data["id"] > 0
    assert data["create_time"]
    assert "password" not in data


# ---- 弱密码校验（校验层拦截 → 422）----

async def test_register_weak_blacklist_422(client: httpx.AsyncClient, username: str) -> None:
    """命中弱口令黑名单 → 422。"""
    resp = await _register(client, username, "12345678")
    assert resp.status_code == 422
    assert resp.json()["code"] == 422


async def test_register_no_digit_422(client: httpx.AsyncClient, username: str) -> None:
    """只含字母、无数字 → 422。"""
    resp = await _register(client, username, "abcdefgh")
    assert resp.status_code == 422
    assert resp.json()["code"] == 422


async def test_register_no_letter_422(client: httpx.AsyncClient, username: str) -> None:
    """只含数字、无字母 → 422。"""
    resp = await _register(client, username, "1234567890")
    assert resp.status_code == 422
    assert resp.json()["code"] == 422


async def test_register_contains_username_422(client: httpx.AsyncClient, username: str) -> None:
    """密码包含用户名（大小写不敏感）→ 422。"""
    resp = await _register(client, username, f"{username}9x")
    assert resp.status_code == 422
    assert resp.json()["code"] == 422


# ---- 业务冲突 ----

async def test_register_duplicate_409(client: httpx.AsyncClient, username: str) -> None:
    """同名注册两次，第二次返回 409。"""
    assert (await _register(client, username)).status_code == 200
    resp = await _register(client, username)
    assert resp.status_code == 409
    assert resp.json()["code"] == 409


# ---- 限流（固定窗口 + IP 维度）----

async def test_register_rate_limited_429(client: httpx.AsyncClient, username: str) -> None:
    """同一 IP 连续注册，超过 5 次/min 的第 6 次返回 429。"""
    # 用 username 夹具派生唯一名字，保证仍带 TEST_PREFIX 会被自动清理
    for i in range(rate_limit.MAX_REQUESTS):
        resp = await _register(client, f"{username}_{i}")
        assert resp.status_code == 200, f"第 {i + 1} 次应放行"
    resp = await _register(client, f"{username}_overflow")
    assert resp.status_code == 429
    assert resp.json()["code"] == 429
