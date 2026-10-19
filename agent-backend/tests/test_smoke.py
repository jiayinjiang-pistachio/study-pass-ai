"""用户接口冒烟测试：覆盖健康检查与用户 CRUD 主路径 + 常见错误路径。

运行：pytest tests/test_smoke.py -v
依赖：本地 MySQL 已启动且执行过 alembic upgrade head。
"""

import httpx

from app.db import health_repo

VALID_PASSWORD = "secret123"


async def _create_user(client: httpx.AsyncClient, username: str, headers: dict) -> dict:
    """建用户并返回 data，供需要已存在用户的用例复用。"""
    resp = await client.post(
        "/api/users", json={"username": username, "password": VALID_PASSWORD}, headers=headers
    )
    assert resp.status_code == 200
    return resp.json()["data"]


# ---- 健康检查 ----

async def test_health_ok(client: httpx.AsyncClient) -> None:
    """数据库正常时，健康检查返回 200 且标明 database=up。"""
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 200
    assert body["data"] == {"status": "ok", "database": "up"}


async def test_health_db_down_returns_503(client: httpx.AsyncClient, monkeypatch) -> None:
    """数据库探活抛错时，健康检查返回 503（不真的停库，用 monkeypatch 模拟）。"""

    def boom() -> None:
        raise RuntimeError("simulated db down")

    monkeypatch.setattr(health_repo, "ping", boom)
    resp = await client.get("/health")
    assert resp.status_code == 503
    assert resp.json()["code"] == 503


# ---- 用户 CRUD（需鉴权）----

async def test_users_requires_auth_401(client: httpx.AsyncClient) -> None:
    """未带令牌访问受保护的用户接口返回 401。"""
    resp = await client.get("/api/users")
    assert resp.status_code == 401
    assert resp.json()["code"] == 401


async def test_create_user(client: httpx.AsyncClient, username: str, auth_headers: dict) -> None:
    """创建用户返回 200，含 id/create_time，且响应不含密码。"""
    resp = await client.post(
        "/api/users", json={"username": username, "password": VALID_PASSWORD}, headers=auth_headers
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["username"] == username
    assert data["id"] > 0
    assert data["create_time"]
    assert "password" not in data


async def test_create_duplicate_username_409(client: httpx.AsyncClient, username: str, auth_headers: dict) -> None:
    """用户名重复返回 409。"""
    await _create_user(client, username, auth_headers)
    resp = await client.post(
        "/api/users", json={"username": username, "password": VALID_PASSWORD}, headers=auth_headers
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == 409


async def test_create_invalid_payload_422(client: httpx.AsyncClient, username: str, auth_headers: dict) -> None:
    """密码过短由校验层拦截，返回 422。"""
    resp = await client.post(
        "/api/users", json={"username": username, "password": "123"}, headers=auth_headers
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == 422


async def test_get_user_ok(client: httpx.AsyncClient, username: str, auth_headers: dict) -> None:
    """按 id 查询已存在用户返回 200。"""
    created = await _create_user(client, username, auth_headers)
    resp = await client.get(f"/api/users/{created['id']}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["username"] == username


async def test_get_user_not_found_404(client: httpx.AsyncClient, auth_headers: dict) -> None:
    """查询不存在的用户返回 404。"""
    resp = await client.get("/api/users/999999999", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["code"] == 404


async def test_list_users(client: httpx.AsyncClient, username: str, auth_headers: dict) -> None:
    """列表接口返回 200，data 为列表且包含刚创建的用户。"""
    created = await _create_user(client, username, auth_headers)
    resp = await client.get("/api/users", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert isinstance(data, list)
    assert any(u["id"] == created["id"] for u in data)


async def test_update_user(client: httpx.AsyncClient, username: str, auth_headers: dict) -> None:
    """更新用户名返回 200 且字段已生效。"""
    created = await _create_user(client, username, auth_headers)
    new_name = f"{username}x"[:32]
    resp = await client.put(
        f"/api/users/{created['id']}", json={"username": new_name}, headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["username"] == new_name


async def test_delete_user(client: httpx.AsyncClient, username: str, auth_headers: dict) -> None:
    """删除返回 200，再次删除同一用户返回 404。"""
    created = await _create_user(client, username, auth_headers)
    resp = await client.delete(f"/api/users/{created['id']}", headers=auth_headers)
    assert resp.status_code == 200
    again = await client.delete(f"/api/users/{created['id']}", headers=auth_headers)
    assert again.status_code == 404
