"""会话 / 聊天消息 / 面试详情接口测试。

覆盖：分页、创建、编辑、越权隔离、消息字段语义、面试详情、级联删除。
依赖本地 MySQL（先 alembic upgrade head）；级联删除用例还依赖 MinIO。
"""

import hashlib

import httpx

from app.core import minio_client
from app.db import interview_repo, message_repo, resource_repo, session_repo


def _new_session(user_id: int, title: str = "会话", session_mode: int = 0) -> dict:
    """直接落库造会话，避免用例依赖创建接口。"""
    return session_repo.insert(
        {"user_id": user_id, "title": title, "session_mode": session_mode}
    )


def _new_message(
    user_id: int,
    session_id: int,
    request_text: str,
    response_text: str = "AI 回复",
    request_segments: list[dict] | None = None,
    response_segments: list[dict] | None = None,
    status: int = 1,
    interview_id: int | None = None,
) -> dict:
    """直接落库造消息；附件段与正文严格分开。"""
    return message_repo.insert(
        {
            "user_id": user_id,
            "session_id": session_id,
            "select_mode": 0,
            "request_id": f"req-{user_id}-{session_id}-{request_text}",
            "request_text": request_text,
            "response_text": response_text,
            "request_segments": request_segments,
            "response_segments": response_segments,
            "status": status,
            "interview_id": interview_id,
        }
    )


# ---- 鉴权 ----

async def test_sessions_require_login(client: httpx.AsyncClient) -> None:
    """未携带令牌访问会话接口 → 401。"""
    resp = await client.get("/api/sessions")
    assert resp.status_code == 401
    assert resp.json()["code"] == 401


# ---- 创建会话 ----

async def test_create_session(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    """创建会话返回 id/title/session_mode/created_at，且不暴露 user_id。"""
    resp = await client.post(
        "/api/sessions", headers=auth_headers, json={"title": "学习会话", "session_mode": 0}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["id"] > 0
    assert data["title"] == "学习会话"
    assert data["session_mode"] == 0
    assert data["created_at"] > 0
    assert "user_id" not in data


async def test_create_session_accepts_session_model_alias(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    """兼容需求文档中的 session_model 字段名。"""
    resp = await client.post(
        "/api/sessions",
        headers=auth_headers,
        json={"title": "面试会话", "session_model": 1},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["session_mode"] == 1


async def test_create_session_invalid_mode_422(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    """会话模式超出 0..2 → 422。"""
    resp = await client.post(
        "/api/sessions", headers=auth_headers, json={"title": "x", "session_mode": 3}
    )
    assert resp.status_code == 422


# ---- 会话列表 ----

async def test_list_sessions_pagination_and_order(
    client: httpx.AsyncClient, auth_user: dict, auth_headers: dict
) -> None:
    """按创建时间倒序返回，分页 total/page/page_size 正确。"""
    first = _new_session(auth_user["id"], "第一个")
    second = _new_session(auth_user["id"], "第二个")
    third = _new_session(auth_user["id"], "第三个")

    resp = await client.get(
        "/api/sessions", headers=auth_headers, params={"page": 1, "page_size": 2}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["total"] == 3
    assert data["page"] == 1
    assert data["page_size"] == 2
    assert [item["id"] for item in data["items"]] == [third["id"], second["id"]]

    resp = await client.get(
        "/api/sessions", headers=auth_headers, params={"page": 2, "page_size": 2}
    )
    assert [item["id"] for item in resp.json()["data"]["items"]] == [first["id"]]


async def test_list_sessions_isolated_by_user(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    other_auth: tuple[dict, dict],
) -> None:
    """他人会话不出现在当前用户的列表中。"""
    _new_session(auth_user["id"], "我的会话")
    other_user, _ = other_auth
    _new_session(other_user["id"], "别人的会话")

    resp = await client.get("/api/sessions", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] == 1
    assert resp.json()["data"]["items"][0]["title"] == "我的会话"


async def test_list_sessions_filters_by_mode(
    client: httpx.AsyncClient, auth_user: dict, auth_headers: dict
) -> None:
    """session_mode 过滤后 items 与 total 都只统计该模式。"""
    _new_session(auth_user["id"], "学习会话", 0)
    interview = _new_session(auth_user["id"], "面试会话", 1)
    _new_session(auth_user["id"], "笔记会话", 2)

    resp = await client.get(
        "/api/sessions", headers=auth_headers, params={"session_mode": 1}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["total"] == 1
    assert [item["id"] for item in data["items"]] == [interview["id"]]


async def test_list_sessions_invalid_mode_422(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    """会话模式超出 0..2 → 422。"""
    resp = await client.get(
        "/api/sessions", headers=auth_headers, params={"session_mode": 3}
    )
    assert resp.status_code == 422


# ---- 编辑会话 ----

async def test_update_session_title(
    client: httpx.AsyncClient, auth_user: dict, auth_headers: dict
) -> None:
    """修改自己的会话标题成功。"""
    session = _new_session(auth_user["id"], "旧标题")
    resp = await client.put(
        f"/api/sessions/{session['id']}",
        headers=auth_headers,
        json={"title": "新标题"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["title"] == "新标题"
    assert session_repo.get(session["id"])["title"] == "新标题"


async def test_update_other_user_session_404(
    client: httpx.AsyncClient,
    auth_user: dict,
    other_auth: tuple[dict, dict],
) -> None:
    """修改他人会话 → 404（不泄露会话是否存在）。"""
    _, other_headers = other_auth
    session = _new_session(auth_user["id"], "私有会话")
    resp = await client.put(
        f"/api/sessions/{session['id']}",
        headers=other_headers,
        json={"title": "篡改"},
    )
    assert resp.status_code == 404
    assert session_repo.get(session["id"])["title"] == "私有会话"


# ---- 消息列表 ----

async def test_list_messages_fields_and_pagination(
    client: httpx.AsyncClient, auth_user: dict, auth_headers: dict
) -> None:
    """消息按时间正序分页，返回正文 / 双附件段 / status / interview_id。"""
    session = _new_session(auth_user["id"])
    segment = {
        "type": "file",
        "resource_id": 101,
        "file_name": "a.pdf",
        "url": None,
    }
    _new_message(
        auth_user["id"],
        session["id"],
        "第一问",
        "第一答",
        request_segments=[segment],
        interview_id=None,
    )
    _new_message(auth_user["id"], session["id"], "第二问", "第二答", status=0)
    third = _new_message(
        auth_user["id"],
        session["id"],
        "第三问",
        "第三答",
        response_segments=[{"type": "image", "resource_id": 102}],
        interview_id=7,
    )

    resp = await client.get(
        f"/api/sessions/{session['id']}/messages",
        headers=auth_headers,
        params={"page": 1, "page_size": 2},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["total"] == 3
    assert len(data["items"]) == 2

    first = data["items"][0]
    assert first["request_text"] == "第一问"
    # request_id 供前端识别测评消息，普通聊天原样透传
    assert first["request_id"] == f"req-{auth_user['id']}-{session['id']}-第一问"
    assert first["response_text"] == "第一答"
    assert first["request_segments"] == [segment]
    assert first["response_segments"] == []
    assert first["status"] == 1
    assert first["interview_id"] is None
    assert first["created_at"] > 0

    resp = await client.get(
        f"/api/sessions/{session['id']}/messages",
        headers=auth_headers,
        params={"page": 2, "page_size": 2},
    )
    last = resp.json()["data"]["items"][0]
    assert last["id"] == third["id"]
    assert last["request_segments"] == []
    assert last["response_segments"] == [
        {"type": "image", "resource_id": 102, "file_name": None, "url": None}
    ]
    assert last["interview_id"] == 7


async def test_list_messages_missing_session_404(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    """不存在的会话 → 404。"""
    resp = await client.get("/api/sessions/999999999/messages", headers=auth_headers)
    assert resp.status_code == 404


async def test_list_messages_other_user_404(
    client: httpx.AsyncClient,
    auth_user: dict,
    other_auth: tuple[dict, dict],
) -> None:
    """读取他人会话消息 → 404。"""
    _, other_headers = other_auth
    session = _new_session(auth_user["id"])
    _new_message(auth_user["id"], session["id"], "私密问题")
    resp = await client.get(
        f"/api/sessions/{session['id']}/messages", headers=other_headers
    )
    assert resp.status_code == 404


# ---- 面试详情 ----

def _new_interview(user_id: int, session_id: int, message_id: int) -> dict:
    return interview_repo.insert(
        {
            "user_id": user_id,
            "session_id": session_id,
            "message_id": message_id,
            "qa_object": [{"id": 1, "question": "Q", "answer": "A", "created_at": 1}],
            "interview_duration": 60,
            "status": 0,
        }
    )


async def test_get_interview_detail(
    client: httpx.AsyncClient, auth_user: dict, auth_headers: dict
) -> None:
    """按 interview_id + user_id 返回含 qa_object 的详情。"""
    session = _new_session(auth_user["id"], session_mode=1)
    message = _new_message(auth_user["id"], session["id"], "开始面试")
    interview = _new_interview(auth_user["id"], session["id"], message["id"])

    resp = await client.get(
        f"/api/interviews/{interview['id']}", headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["id"] == interview["id"]
    assert data["session_id"] == session["id"]
    assert data["message_id"] == message["id"]
    assert data["qa_object"][0]["question"] == "Q"
    assert data["interview_duration"] == 60
    assert "user_id" not in data


async def test_get_interview_other_user_404(
    client: httpx.AsyncClient,
    auth_user: dict,
    other_auth: tuple[dict, dict],
) -> None:
    """他人的面试记录 → 404。"""
    _, other_headers = other_auth
    session = _new_session(auth_user["id"], session_mode=1)
    message = _new_message(auth_user["id"], session["id"], "开始面试")
    interview = _new_interview(auth_user["id"], session["id"], message["id"])

    resp = await client.get(
        f"/api/interviews/{interview['id']}", headers=other_headers
    )
    assert resp.status_code == 404


# ---- 级联删除 ----

def _new_resource(user_id: int, filename: str, content: bytes, suffix: str) -> tuple[dict, str]:
    """造一条资源元数据并在 MinIO 写入对象。"""
    md5 = hashlib.md5(content, usedforsecurity=False).hexdigest()
    key = f"users/{user_id}/{md5}{suffix}"
    minio_client.put_object(key, content, "application/octet-stream")
    resource = resource_repo.insert(
        {
            "resource_type": 0,
            "storage_scene": 0,
            "upload_purpose": 0,
            "file_name": filename,
            "file_hash": md5,
            "storage_path": minio_client.build_storage_path(key),
            "user_id": user_id,
            "expire_time": None,
        }
    )
    return resource, key


async def test_delete_session_cascades(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    minio_ready: None,
) -> None:
    """删除会话 → 消息、面试、附件资源元数据与 MinIO 对象一并删除。"""
    session = _new_session(auth_user["id"], session_mode=1)
    request_resource, request_key = _new_resource(
        auth_user["id"], "question.pdf", b"%PDF-1.4\nquestion", ".pdf"
    )
    response_resource, response_key = _new_resource(
        auth_user["id"], "answer.pdf", b"%PDF-1.4\nanswer", ".pdf"
    )

    message = _new_message(
        auth_user["id"],
        session["id"],
        "请看附件",
        "已生成附件",
        request_segments=[
            {
                "type": "file",
                "resource_id": request_resource["id"],
                "file_name": "question.pdf",
            }
        ],
        response_segments=[
            {"type": "file", "resource_id": str(response_resource["id"])}
        ],
    )
    interview = _new_interview(auth_user["id"], session["id"], message["id"])

    resp = await client.delete(f"/api/sessions/{session['id']}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"] is None

    assert session_repo.get(session["id"]) is None
    assert message_repo.get(message["id"]) is None
    assert interview_repo.get(interview["id"]) is None
    assert resource_repo.get(request_resource["id"]) is None
    assert resource_repo.get(response_resource["id"]) is None
    assert not minio_client.object_exists(request_key)
    assert not minio_client.object_exists(response_key)


async def test_delete_session_keeps_other_users_resource(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    other_auth: tuple[dict, dict],
) -> None:
    """附件段里若混入他人 resource_id，不删除他人的资源。"""
    other_user, _ = other_auth
    session = _new_session(auth_user["id"])
    other_resource = resource_repo.insert(
        {
            "resource_type": 0,
            "storage_scene": 2,
            "upload_purpose": 0,
            "file_name": "other.txt",
            "file_hash": hashlib.md5(b"other", usedforsecurity=False).hexdigest(),
            "storage_path": "",
            "user_id": other_user["id"],
            "expire_time": None,
        }
    )
    _new_message(
        auth_user["id"],
        session["id"],
        "越权引用",
        request_segments=[{"type": "file", "resource_id": other_resource["id"]}],
    )

    resp = await client.delete(f"/api/sessions/{session['id']}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resource_repo.get(other_resource["id"]) is not None


async def test_delete_other_user_session_404(
    client: httpx.AsyncClient,
    auth_user: dict,
    other_auth: tuple[dict, dict],
) -> None:
    """删除他人会话 → 404，且会话仍然存在。"""
    _, other_headers = other_auth
    session = _new_session(auth_user["id"], "别人的会话")
    resp = await client.delete(
        f"/api/sessions/{session['id']}", headers=other_headers
    )
    assert resp.status_code == 404
    assert session_repo.get(session["id"]) is not None
