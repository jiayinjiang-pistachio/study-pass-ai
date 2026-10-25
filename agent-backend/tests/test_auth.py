"""鉴权接口冒烟测试：注册（弱密码 / 重复 / 限流）+ 登录 / 刷新 / 当前用户。

运行：pytest tests/test_auth.py -v
依赖：本地 MySQL 已启动且执行过 alembic upgrade head。
"""

import hashlib
from datetime import datetime, timedelta

import httpx

from app.core import minio_client, rate_limit
from app.core.config import AVATAR_MAX_BYTES, get_minio_config
from app.core.security import create_access_token
from app.db import resource_repo

VALID_PASSWORD = "abc12345"
PNG_BYTES = b"\x89PNG\r\n\x1a\nfake-avatar"
PDF_BYTES = b"%PDF-1.4\nfake-pdf"
DOC_BYTES = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1fake-doc"
DOCX_BYTES = b"PK\x03\x04fake-docx"
TXT_BYTES = "面试笔记：Redis 缓存穿透".encode()
WAV_BYTES = b"RIFF\x24\x00\x00\x00WAVEfmt fake-audio"


def _object_key(user_id: int, md5: str, suffix: str) -> str:
    return f"users/{user_id}/{md5}{suffix}"


def _storage_path(user_id: int, md5: str, suffix: str) -> str:
    return f"minio:/{get_minio_config().bucket}/{_object_key(user_id, md5, suffix)}"


async def _post_file(
    client: httpx.AsyncClient,
    headers: dict,
    filename: str,
    content: bytes,
    content_type: str,
    **form: str,
) -> httpx.Response:
    return await client.post(
        "/api/files",
        headers=headers,
        files={"file": (filename, content, content_type)},
        data=form or None,
    )


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

async def test_upload_avatar_image_stores_object_and_updates_avatar(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    minio_ready: None,
) -> None:
    """头像图片 → 写 resources + MinIO 对象，并更新 users.avatar。"""
    resp = await _post_file(
        client,
        auth_headers,
        "avatar.png",
        PNG_BYTES,
        "image/png",
        upload_purpose="1",
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    md5 = hashlib.md5(PNG_BYTES).hexdigest()
    expected = _storage_path(auth_user["id"], md5, ".png")

    assert data["kind"] == "image"
    assert data["resource_id"] > 0
    assert data["storage_path"] == expected
    assert data["url"] == expected
    assert data["expire_time"] is None
    assert minio_client.object_exists(_object_key(auth_user["id"], md5, ".png"))

    resource = resource_repo.get(data["resource_id"])
    assert resource is not None
    assert resource["resource_type"] == 1
    assert resource["upload_purpose"] == 1
    assert resource["file_hash"] == md5

    # 响应中的 avatar 是浏览器可访问的地址，而不是 MinIO 内部路径
    me = await client.get("/api/auth/me", headers=auth_headers)
    assert me.json()["data"]["avatar"] == (
        f"/api/files/avatar/{auth_user['id']}?v={md5}"
    )


async def test_avatar_is_publicly_readable(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    minio_ready: None,
) -> None:
    """头像读取接口无需令牌：浏览器 <img src> 可以直接访问。"""
    await _post_file(
        client,
        auth_headers,
        "avatar.png",
        PNG_BYTES,
        "image/png",
        upload_purpose="1",
    )

    resp = await client.get(f"/api/files/avatar/{auth_user['id']}")
    assert resp.status_code == 200
    assert resp.content == PNG_BYTES
    assert resp.headers["content-type"] == "image/png"


async def test_avatar_missing_404(
    client: httpx.AsyncClient, auth_user: dict
) -> None:
    """未上传头像时读取 → 404。"""
    resp = await client.get(f"/api/files/avatar/{auth_user['id']}")
    assert resp.status_code == 404
    assert resp.json()["code"] == 404


async def test_upload_document_stores_object_without_updating_avatar(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    minio_ready: None,
    stub_rag_ingest: list[dict],
) -> None:
    """文档 → 只存资源和对象，不修改 avatar；长期场景约 30 天过期并异步接入 RAG。"""
    resp = await _post_file(
        client,
        auth_headers,
        "report.pdf",
        PDF_BYTES,
        "application/pdf",
        doc_category="resume",
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    md5 = hashlib.md5(PDF_BYTES).hexdigest()

    assert data["kind"] == "document"
    assert data["doc_category"] == "resume"
    assert data["reused"] is False
    assert data["storage_path"] == _storage_path(auth_user["id"], md5, ".pdf")
    assert minio_client.object_exists(_object_key(auth_user["id"], md5, ".pdf"))

    remaining = datetime.fromisoformat(data["expire_time"]) - datetime.now()
    assert timedelta(days=29) < remaining <= timedelta(days=30, minutes=5)

    resource = resource_repo.get(data["resource_id"])
    assert resource is not None
    assert resource["doc_category"] == "resume"

    assert len(stub_rag_ingest) == 1
    call = stub_rag_ingest[0]
    assert call["content"] == PDF_BYTES
    assert call["suffix"] == ".pdf"
    assert call["doc_category"] == "resume"
    assert call["resource_id"] == data["resource_id"]
    assert call["replace"] is False

    me = await client.get("/api/auth/me", headers=auth_headers)
    assert me.json()["data"]["avatar"] is None


async def test_upload_doc_docx_and_txt_documents(
    client: httpx.AsyncClient,
    auth_headers: dict,
    minio_ready: None,
) -> None:
    """DOC / DOCX / TXT 在白名单内 → 200，kind=document，分类原样返回。"""
    doc = await _post_file(
        client,
        auth_headers,
        "resume.doc",
        DOC_BYTES,
        "application/msword",
        doc_category="resume",
    )
    docx = await _post_file(
        client,
        auth_headers,
        "resume.docx",
        DOCX_BYTES,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        doc_category="resume",
    )
    txt = await _post_file(
        client,
        auth_headers,
        "notes.txt",
        TXT_BYTES,
        "text/plain",
        doc_category="study_material",
    )

    assert doc.status_code == 200, doc.text
    assert doc.json()["data"]["kind"] == "document"
    assert doc.json()["data"]["doc_category"] == "resume"
    assert docx.status_code == 200, docx.text
    assert docx.json()["data"]["kind"] == "document"
    assert docx.json()["data"]["doc_category"] == "resume"
    assert txt.status_code == 200, txt.text
    assert txt.json()["data"]["kind"] == "document"
    assert txt.json()["data"]["doc_category"] == "study_material"


async def test_upload_audio_stores_object_as_audio_resource(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    minio_ready: None,
    stub_rag_ingest: list[dict],
) -> None:
    """音频 → resource_type=2、kind=audio；doc_category 被忽略且不触发 RAG。"""
    resp = await _post_file(
        client,
        auth_headers,
        "voice.wav",
        WAV_BYTES,
        "audio/wav",
        doc_category="resume",
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    md5 = hashlib.md5(WAV_BYTES).hexdigest()

    assert data["kind"] == "audio"
    assert data["doc_category"] is None
    assert data["storage_path"] == _storage_path(auth_user["id"], md5, ".wav")
    assert minio_client.object_exists(_object_key(auth_user["id"], md5, ".wav"))

    resource = resource_repo.get(data["resource_id"])
    assert resource is not None
    assert resource["resource_type"] == 2
    assert resource["doc_category"] is None
    assert stub_rag_ingest == []

    me = await client.get("/api/auth/me", headers=auth_headers)
    assert me.json()["data"]["avatar"] is None


async def test_upload_forged_audio_422(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    """扩展名为 .wav 但文件头不符 → 422。"""
    resp = await client.post(
        "/api/files",
        headers=auth_headers,
        files={"file": ("voice.wav", b"<html>fake</html>", "audio/wav")},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == 422


async def test_upload_forged_docx_422(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    """扩展名为 .docx 但文件头不符 → 422。"""
    resp = await client.post(
        "/api/files",
        headers=auth_headers,
        files={"file": ("resume.docx", b"<html>fake</html>", "application/msword")},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == 422


async def test_upload_document_requires_doc_category_422(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    """文档必须显式传 doc_category，否则 422。"""
    resp = await _post_file(
        client, auth_headers, "report.pdf", PDF_BYTES, "application/pdf"
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == 422


async def test_upload_document_invalid_doc_category_422(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    """doc_category 不在枚举内 → 422（表单校验）。"""
    resp = await _post_file(
        client,
        auth_headers,
        "report.pdf",
        PDF_BYTES,
        "application/pdf",
        doc_category="unknown",
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == 422


async def test_upload_same_content_is_deduplicated(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    minio_ready: None,
    stub_rag_ingest: list[dict],
) -> None:
    """同用户同内容同分类重复上传 → 复用资源记录且不重复入库。"""
    first = await _post_file(
        client,
        auth_headers,
        "a.pdf",
        PDF_BYTES,
        "application/pdf",
        doc_category="resume",
    )
    second = await _post_file(
        client,
        auth_headers,
        "b.pdf",
        PDF_BYTES,
        "application/pdf",
        doc_category="resume",
    )

    assert first.status_code == 200 and second.status_code == 200
    first_data = first.json()["data"]
    second_data = second.json()["data"]
    assert first_data["reused"] is False
    assert second_data["reused"] is True
    assert first_data["resource_id"] == second_data["resource_id"]
    assert first_data["storage_path"] == second_data["storage_path"]
    assert second_data["doc_category"] == "resume"

    rows = resource_repo.list_by_user(auth_user["id"])
    assert len(rows) == 1
    assert rows[0]["file_name"] == "a.pdf"
    assert len(stub_rag_ingest) == 1


async def test_upload_same_content_different_category_reingests(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    minio_ready: None,
    stub_rag_ingest: list[dict],
) -> None:
    """重复上传但分类变化 → 更新 doc_category 并以 replace=True 重新入库。"""
    first = await _post_file(
        client,
        auth_headers,
        "a.pdf",
        PDF_BYTES,
        "application/pdf",
        doc_category="resume",
    )
    second = await _post_file(
        client,
        auth_headers,
        "b.pdf",
        PDF_BYTES,
        "application/pdf",
        doc_category="study_material",
    )

    assert first.status_code == 200 and second.status_code == 200
    first_data = first.json()["data"]
    second_data = second.json()["data"]
    assert second_data["reused"] is True
    assert second_data["resource_id"] == first_data["resource_id"]
    assert second_data["doc_category"] == "study_material"

    rows = resource_repo.list_by_user(auth_user["id"])
    assert len(rows) == 1
    assert rows[0]["doc_category"] == "study_material"

    assert len(stub_rag_ingest) == 2
    assert stub_rag_ingest[0]["replace"] is False
    assert stub_rag_ingest[1]["replace"] is True
    assert stub_rag_ingest[1]["resource_id"] == first_data["resource_id"]
    assert stub_rag_ingest[1]["doc_category"] == "study_material"


async def test_upload_short_scene_sets_two_hour_expiry(
    client: httpx.AsyncClient,
    auth_headers: dict,
    minio_ready: None,
) -> None:
    """storage_scene=1 → 过期时间约为 2 小时后。"""
    resp = await _post_file(
        client,
        auth_headers,
        "short.pdf",
        PDF_BYTES,
        "application/pdf",
        storage_scene="1",
        doc_category="general",
    )
    assert resp.status_code == 200, resp.text

    remaining = datetime.fromisoformat(resp.json()["data"]["expire_time"]) - datetime.now()
    assert timedelta(hours=1, minutes=59) <= remaining <= timedelta(hours=2, minutes=1)


async def test_upload_extract_only_scene_skips_object(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    minio_ready: None,
) -> None:
    """storage_scene=2 → 只写元数据，不落 MinIO，storage_path 为空且不过期。"""
    resp = await _post_file(
        client,
        auth_headers,
        "extract.pdf",
        PDF_BYTES,
        "application/pdf",
        storage_scene="2",
        doc_category="general",
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    md5 = hashlib.md5(PDF_BYTES).hexdigest()

    assert data["storage_path"] == ""
    assert data["url"] == ""
    assert data["expire_time"] is None
    assert not minio_client.object_exists(_object_key(auth_user["id"], md5, ".pdf"))


async def test_upload_image_without_avatar_purpose_422(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    """图片仅用于头像；upload_purpose=0 的图片 → 422。"""
    resp = await _post_file(
        client, auth_headers, "photo.png", PNG_BYTES, "image/png"
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == 422


async def test_upload_invalid_purpose_422(
    client: httpx.AsyncClient, auth_headers: dict, minio_ready: None
) -> None:
    """upload_purpose 超出 0/1 → 422（表单校验）。"""
    resp = await _post_file(
        client,
        auth_headers,
        "avatar.png",
        PNG_BYTES,
        "image/png",
        upload_purpose="2",
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == 422


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
    """头像图片超过 2MB → 413。"""
    oversized = PNG_BYTES + b"x" * (AVATAR_MAX_BYTES + 1 - len(PNG_BYTES))
    resp = await client.post(
        "/api/files",
        headers=auth_headers,
        files={"file": ("avatar.png", oversized, "image/png")},
        data={"upload_purpose": "1"},
    )
    assert resp.status_code == 413
    assert resp.json()["code"] == 413


# ---- 受保护的用户 CRUD ----

async def test_users_requires_auth_401(client: httpx.AsyncClient) -> None:
    """未带令牌访问 /api/users → 401。"""
    resp = await client.get("/api/users")
    assert resp.status_code == 401
    assert resp.json()["code"] == 401
