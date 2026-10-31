"""笔记管理 CRUD 接口测试。

覆盖：鉴权、创建 / 详情 / 列表 / 局部更新 / 删除、类型过滤与关键词检索、
用户隔离、会话归属校验、字段校验。
"""

import httpx

from app.db import session_repo

BASE = "/api/notes"


def _create_session(user_id: int) -> dict:
    return session_repo.insert(
        {"user_id": user_id, "title": "笔记会话", "session_mode": 2}
    )


def _payload(session_id: int, **overrides) -> dict:
    payload = {
        "session_id": session_id,
        "note_type": "manual",
        "title": "数据库复习",
        "content": "# 数据库复习\n索引原理与 B+ 树。",
        "tags": ["数据库"],
        "metadata": {"source": "manual"},
    }
    payload.update(overrides)
    return payload


async def test_notes_require_login(client: httpx.AsyncClient) -> None:
    """未携带令牌 → 401。"""
    resp = await client.get(BASE)
    assert resp.status_code == 401


async def test_note_crud_flow(
    client: httpx.AsyncClient, auth_user: dict, auth_headers: dict
) -> None:
    """创建 → 详情 → 列表 → 局部更新 → 删除。"""
    session = _create_session(auth_user["id"])

    resp = await client.post(BASE, headers=auth_headers, json=_payload(session["id"]))
    assert resp.status_code == 200, resp.text
    created = resp.json()["data"]
    assert created["title"] == "数据库复习"
    assert created["tags"] == ["数据库"]
    assert created["metadata"] == {"source": "manual"}
    assert "user_id" not in created

    resp = await client.get(f"{BASE}/{created['id']}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["content"].startswith("# 数据库复习")

    resp = await client.get(BASE, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    listing = resp.json()["data"]
    assert listing["total"] == 1
    assert listing["items"][0]["id"] == created["id"]
    # 列表不返回正文，避免分页响应过大
    assert "content" not in listing["items"][0]

    resp = await client.put(
        f"{BASE}/{created['id']}",
        headers=auth_headers,
        json={"title": "新标题"},
    )
    assert resp.status_code == 200, resp.text
    updated = resp.json()["data"]
    assert updated["title"] == "新标题"
    assert updated["content"].startswith("# 数据库复习")

    resp = await client.delete(f"{BASE}/{created['id']}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"] is None

    resp = await client.get(f"{BASE}/{created['id']}", headers=auth_headers)
    assert resp.status_code == 404


async def test_note_list_filters(
    client: httpx.AsyncClient, auth_user: dict, auth_headers: dict
) -> None:
    """按 note_type 过滤；keyword 同时命中标题与正文。"""
    session = _create_session(auth_user["id"])
    assert (
        await client.post(
            BASE,
            headers=auth_headers,
            json=_payload(
                session["id"],
                note_type="learning_quiz",
                title="数据库索引复习",
                content="B+ 树与回表。",
            ),
        )
    ).status_code == 200
    assert (
        await client.post(
            BASE,
            headers=auth_headers,
            json=_payload(
                session["id"],
                title="前端复习",
                content="数据库连接池。",
            ),
        )
    ).status_code == 200

    resp = await client.get(
        BASE, headers=auth_headers, params={"note_type": "learning_quiz"}
    )
    assert resp.json()["data"]["total"] == 1

    resp = await client.get(BASE, headers=auth_headers, params={"keyword": "索引"})
    assert resp.json()["data"]["total"] == 1

    # 「数据库」既出现在一条标题中，也出现在另一条正文中
    resp = await client.get(BASE, headers=auth_headers, params={"keyword": "数据库"})
    assert resp.json()["data"]["total"] == 2

    # % 不应被当成通配符
    resp = await client.get(BASE, headers=auth_headers, params={"keyword": "%"})
    assert resp.json()["data"]["total"] == 0


async def test_note_isolation(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    other_auth: tuple[dict, dict],
) -> None:
    """其他用户看不到、改不了、删不掉当前用户的笔记。"""
    _, other_headers = other_auth
    session = _create_session(auth_user["id"])
    created = (
        await client.post(BASE, headers=auth_headers, json=_payload(session["id"]))
    ).json()["data"]

    assert (
        await client.get(f"{BASE}/{created['id']}", headers=other_headers)
    ).status_code == 404
    assert (
        await client.put(
            f"{BASE}/{created['id']}", headers=other_headers, json={"title": "越权"}
        )
    ).status_code == 404
    assert (
        await client.delete(f"{BASE}/{created['id']}", headers=other_headers)
    ).status_code == 404

    resp = await client.get(BASE, headers=other_headers)
    assert resp.json()["data"]["total"] == 0


async def test_create_note_rejects_foreign_session(
    client: httpx.AsyncClient,
    auth_headers: dict,
    other_auth: tuple[dict, dict],
) -> None:
    """不能往别人的会话里创建笔记。"""
    other_user, _ = other_auth
    foreign_session = _create_session(other_user["id"])

    resp = await client.post(
        BASE, headers=auth_headers, json=_payload(foreign_session["id"])
    )
    assert resp.status_code == 404


async def test_note_validation(
    client: httpx.AsyncClient, auth_user: dict, auth_headers: dict
) -> None:
    """标题 / 正文为空、标签超过 20 项 → 422。"""
    session = _create_session(auth_user["id"])

    for payload in (
        _payload(session["id"], title=" "),
        _payload(session["id"], content=""),
        _payload(session["id"], tags=["tag"] * 21),
    ):
        resp = await client.post(BASE, headers=auth_headers, json=payload)
        assert resp.status_code == 422
