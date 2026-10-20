"""鉴权接口冒烟测试：注册（弱密码 / 重复 / 限流）+ 登录 / 刷新 / 当前用户。

运行：pytest tests/test_auth.py -v
依赖：本地 MySQL 已启动且执行过 alembic upgrade head。
"""

import hashlib
import shutil
from datetime import timedelta
from pathlib import Path

import httpx

from app.core import rate_limit
from app.core.config import AVATAR_MAX_BYTES, UPLOAD_DIR
from app.core.security import create_access_token

VALID_PASSWORD = "abc12345"
PNG_BYTES = b"\x89PNG\r\n\x1a\nfake-avatar"
PDF_BYTES = b"%PDF-1.4\nfake-pdf"


def _user_upload_dir(user_id: int) -> Path:
    return UPLOAD_DIR / "users" / str(user_id)


async def _register(client: httpx.AsyncClient, username: str, password: str = VALID_PASSWORD) -> httpx.Response:
    return await client.post("/api/auth/register", json={"username": username, "password": password})


async def _login(client: httpx.AsyncClient, username: str, password: str = VALID_PASSWORD) -> httpx.Response:
    return await client.post("/api/auth/login", json={"username": username, "password": password})


# ---- 注册：成功路径 ----

async def test_register_ok(client: httpx.AsyncClient, username: str) -> None:
    """合法用户名 + 强密码注册返回 200，含 id/create_time，且不含密码。"""
    resp = await _register(client, username)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["username"] == username
    assert data["id"] > 0
    assert data["create_time"]
    assert "password" not in data


# ---- 注册：弱密码校验（校验层拦截 → 422）----

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


# ---- 注册：业务冲突 ----

async def test_register_duplicate_409(client: httpx.AsyncClient, username: str) -> None:
    """同名注册两次，第二次返回 409。"""
    assert (await _register(client, username)).status_code == 200
    resp = await _register(client, username)
    assert resp.status_code == 409
    assert resp.json()["code"] == 409


# ---- 注册：限流（固定窗口 + IP 维度）----

async def test_register_rate_limited_429(client: httpx.AsyncClient, username: str) -> None:
    """同一 IP 连续注册，超过 5 次/min 的第 6 次返回 429。"""
    # 用 username 夹具派生唯一名字，保证仍带 TEST_PREFIX 会被自动清理
    for i in range(rate_limit.MAX_REQUESTS):
        resp = await _register(client, f"{username}_{i}")
        assert resp.status_code == 200, f"第 {i + 1} 次应放行"
    resp = await _register(client, f"{username}_overflow")
    assert resp.status_code == 429
    assert resp.json()["code"] == 429


# ---- 登录 ----

async def test_login_ok(client: httpx.AsyncClient, username: str) -> None:
    """注册后登录返回 200 + 双令牌。"""
    await _register(client, username)
    resp = await _login(client, username)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["token_type"] == "bearer"


async def test_login_wrong_password_401(client: httpx.AsyncClient, username: str) -> None:
    """密码错误 → 401。"""
    await _register(client, username)
    resp = await _login(client, username, "wrong-pass-9")
    assert resp.status_code == 401
    assert resp.json()["code"] == 401


async def test_login_unknown_user_401(client: httpx.AsyncClient, username: str) -> None:
    """用户不存在 → 401（与密码错误同文案，防用户名枚举）。"""
    resp = await _login(client, username)
    assert resp.status_code == 401
    assert resp.json()["code"] == 401


# ---- 当前用户 /me ----

async def test_me_ok(client: httpx.AsyncClient, auth_user: dict, auth_headers: dict) -> None:
    """携带有效访问令牌访问 /me 返回 200，且用户名匹配。"""
    resp = await client.get("/api/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["username"] == auth_user["username"]
    assert "password" not in data


async def test_me_missing_token_401(client: httpx.AsyncClient) -> None:
    """不带令牌访问 /me → 401。"""
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401
    assert resp.json()["code"] == 401


async def test_me_invalid_token_401(client: httpx.AsyncClient) -> None:
    """伪造令牌 → 401。"""
    resp = await client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert resp.status_code == 401
    assert resp.json()["code"] == 401


async def test_me_expired_access_token_401(client: httpx.AsyncClient, username: str) -> None:
    """已过期的访问令牌 → 401。"""
    from app.db import user_repo

    user = user_repo.insert({"username": username, "password": "x"})
    expired = create_access_token(user["id"], expires_delta=timedelta(seconds=-1))
    resp = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert resp.status_code == 401
    assert resp.json()["code"] == 401


# ---- 刷新令牌 ----

async def test_refresh_ok(client: httpx.AsyncClient, username: str) -> None:
    """用刷新令牌换取新的访问令牌 → 200。"""
    await _register(client, username)
    tokens = (await _login(client, username)).json()["data"]
    resp = await client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["access_token"]
    assert data["refresh_token"]


async def test_refresh_with_access_token_401(client: httpx.AsyncClient, username: str) -> None:
    """拿访问令牌当刷新令牌用 → 401（类型不符）。"""
    await _register(client, username)
    tokens = (await _login(client, username)).json()["data"]
    resp = await client.post("/api/auth/refresh", json={"refresh_token": tokens["access_token"]})
    assert resp.status_code == 401
    assert resp.json()["code"] == 401


# ---- 通用文件上传 ----

async def test_upload_image_saves_md5_file_and_updates_avatar(
    client: httpx.AsyncClient, auth_user: dict, auth_headers: dict
) -> None:
    """图片 → 保存到用户目录（MD5 文件名）并更新 avatar，静态访问可用。"""
    resp = await client.post(
        "/api/files",
        headers=auth_headers,
        files={"file": ("avatar.png", PNG_BYTES, "image/png")},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    md5 = hashlib.md5(PNG_BYTES).hexdigest()
    expected_url = f"/uploads/users/{auth_user['id']}/{md5}.png"

    try:
        assert data == {"url": expected_url, "md5": md5, "size": len(PNG_BYTES), "kind": "image"}
        path = _user_upload_dir(auth_user["id"]) / f"{md5}.png"
        assert path.is_file()

        me = await client.get("/api/auth/me", headers=auth_headers)
        assert me.json()["data"]["avatar"] == expected_url

        static = await client.get(expected_url)
        assert static.status_code == 200
        assert static.content == PNG_BYTES
    finally:
        shutil.rmtree(_user_upload_dir(auth_user["id"]), ignore_errors=True)


async def test_upload_document_saves_without_updating_avatar(
    client: httpx.AsyncClient, auth_user: dict, auth_headers: dict
) -> None:
    """文档 → 只保存文件，不修改 avatar。"""
    resp = await client.post(
        "/api/files",
        headers=auth_headers,
        files={"file": ("report.pdf", PDF_BYTES, "application/pdf")},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    md5 = hashlib.md5(PDF_BYTES).hexdigest()

    try:
        assert data["kind"] == "document"
        assert data["url"] == f"/uploads/users/{auth_user['id']}/{md5}.pdf"
        assert (_user_upload_dir(auth_user["id"]) / f"{md5}.pdf").is_file()

        me = await client.get("/api/auth/me", headers=auth_headers)
        assert me.json()["data"]["avatar"] is None
    finally:
        shutil.rmtree(_user_upload_dir(auth_user["id"]), ignore_errors=True)


async def test_upload_same_content_is_deduplicated(
    client: httpx.AsyncClient, auth_user: dict, auth_headers: dict
) -> None:
    """相同内容重复上传 → 同一个 MD5 文件名，目录内只有一个文件。"""
    first = await client.post(
        "/api/files",
        headers=auth_headers,
        files={"file": ("a.pdf", PDF_BYTES, "application/pdf")},
    )
    second = await client.post(
        "/api/files",
        headers=auth_headers,
        files={"file": ("b.pdf", PDF_BYTES, "application/pdf")},
    )

    try:
        assert first.status_code == 200 and second.status_code == 200
        assert first.json()["data"]["url"] == second.json()["data"]["url"]
        assert len(list(_user_upload_dir(auth_user["id"]).iterdir())) == 1
    finally:
        shutil.rmtree(_user_upload_dir(auth_user["id"]), ignore_errors=True)


async def test_upload_requires_auth_401(client: httpx.AsyncClient) -> None:
    """未带令牌上传 → 401。"""
    resp = await client.post(
        "/api/files",
        files={"file": ("avatar.png", PNG_BYTES, "image/png")},
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == 401


async def test_upload_unsupported_type_422(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    """不在白名单内的类型 → 422。"""
    resp = await client.post(
        "/api/files",
        headers=auth_headers,
        files={"file": ("script.exe", b"MZ-not-allowed", "application/octet-stream")},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == 422


async def test_upload_forged_pdf_422(client: httpx.AsyncClient, auth_headers: dict) -> None:
    """扩展名为 .pdf 但文件头不符 → 422。"""
    resp = await client.post(
        "/api/files",
        headers=auth_headers,
        files={"file": ("report.pdf", b"<html>fake</html>", "application/pdf")},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == 422


async def test_upload_image_too_large_413(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    """图片超过头像上限 2MB → 413。"""
    oversized = PNG_BYTES + b"x" * (AVATAR_MAX_BYTES + 1 - len(PNG_BYTES))
    resp = await client.post(
        "/api/files",
        headers=auth_headers,
        files={"file": ("avatar.png", oversized, "image/png")},
    )
    assert resp.status_code == 413
    assert resp.json()["code"] == 413


# ---- 受保护的用户 CRUD ----

async def test_users_requires_auth_401(client: httpx.AsyncClient) -> None:
    """未带令牌访问 /api/users → 401。"""
    resp = await client.get("/api/users")
    assert resp.status_code == 401
    assert resp.json()["code"] == 401
