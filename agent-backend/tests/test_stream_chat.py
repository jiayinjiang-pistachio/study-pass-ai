"""流式对话接口测试。

模型调用通过假的 LangChain 链路替换，不依赖真实大模型与 API Key；
覆盖：SSE 事件顺序、记忆层上下文、落库状态、越权隔离、生成失败、配置缺失。
"""

import httpx

from app.db import message_repo, session_repo
from app.services import chat_service


class _FakeChain:
    """模拟 LangChain 链路的 astream：按顺序产出增量文本。"""

    def __init__(self, chunks: list[str], captured: list[dict] | None = None) -> None:
        self._chunks = chunks
        self._captured = captured

    async def astream(self, context: dict):
        if self._captured is not None:
            self._captured.append(context)
        for chunk in self._chunks:
            yield chunk


class _FailingChain:
    """产出部分内容后抛错，验证 error 事件与失败落库。"""

    async def astream(self, context: dict):
        yield "部分内容"
        raise RuntimeError("mock provider failure")


def _new_session(user_id: int, session_mode: int = 0) -> dict:
    return session_repo.insert(
        {"user_id": user_id, "title": "流式会话", "session_mode": session_mode}
    )


def _patch_chain(monkeypatch, chain: object) -> None:
    monkeypatch.setattr(
        chat_service.prompt_layer, "build_chat_chain", lambda *args, **kwargs: chain
    )


async def test_stream_chat_success(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    monkeypatch,
) -> None:
    """正常流式：meta → delta → done，历史上下文正确，回复与状态落库。"""
    session = _new_session(auth_user["id"])
    message_repo.insert(
        {
            "user_id": auth_user["id"],
            "session_id": session["id"],
            "select_mode": 0,
            "request_id": "history-1",
            "request_text": "历史问题",
            "response_text": "历史回答",
            "status": 1,
        }
    )

    captured: list[dict] = []
    _patch_chain(monkeypatch, _FakeChain(["你好", "，世界"], captured))

    resp = await client.post(
        f"/api/sessions/{session['id']}/stream-chat",
        headers=auth_headers,
        json={"request_text": "新问题"},
    )

    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert resp.text.index("event: meta") < resp.text.index("event: delta")
    assert resp.text.index("event: delta") < resp.text.index("event: done")
    assert 'data: {"content": "你好"}' in resp.text

    # 记忆层：只带入已完成的历史问答 + 当前问题
    assert len(captured) == 1
    assert [message.content for message in captured[0]["history"]] == [
        "历史问题",
        "历史回答",
    ]
    assert captured[0]["input"] == "新问题"

    messages = message_repo.list_all_by_session(session["id"])
    latest = next(item for item in messages if item["request_text"] == "新问题")
    assert latest["response_text"] == "你好，世界"
    assert latest["status"] == 1
    assert latest["request_id"]


async def test_stream_chat_rejects_foreign_session(
    client: httpx.AsyncClient,
    other_auth: tuple[dict, dict],
    auth_headers: dict,
    monkeypatch,
) -> None:
    """他人会话 → 404，且不会调用模型。"""
    other_user, _ = other_auth
    session = _new_session(other_user["id"])
    _patch_chain(monkeypatch, _FakeChain(["不应被调用"]))

    resp = await client.post(
        f"/api/sessions/{session['id']}/stream-chat",
        headers=auth_headers,
        json={"request_text": "越权测试"},
    )

    assert resp.status_code == 404
    assert resp.json()["code"] == 404
    assert message_repo.count_by_session(session["id"]) == 0


async def test_stream_chat_marks_failed_on_model_error(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    monkeypatch,
) -> None:
    """模型报错：返回 error 事件，已生成的部分内容保留且状态置为 2。"""
    session = _new_session(auth_user["id"])
    _patch_chain(monkeypatch, _FailingChain())

    resp = await client.post(
        f"/api/sessions/{session['id']}/stream-chat",
        headers=auth_headers,
        json={"request_text": "会失败的问题"},
    )

    assert resp.status_code == 200
    assert "event: error" in resp.text
    assert "event: done" not in resp.text

    latest = message_repo.list_all_by_session(session["id"])[0]
    assert latest["request_text"] == "会失败的问题"
    assert latest["response_text"] == "部分内容"
    assert latest["status"] == 2


async def test_stream_chat_returns_503_without_llm_config(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    monkeypatch,
) -> None:
    """模型配置缺失：建立流之前返回 503，不留下脏消息。"""
    session = _new_session(auth_user["id"])

    def _raise(*args, **kwargs):
        raise RuntimeError("LLM_API_KEY 未配置")

    monkeypatch.setattr(chat_service.prompt_layer, "build_chat_chain", _raise)

    resp = await client.post(
        f"/api/sessions/{session['id']}/stream-chat",
        headers=auth_headers,
        json={"request_text": "配置缺失"},
    )

    assert resp.status_code == 503
    assert resp.json()["code"] == 503
    assert message_repo.count_by_session(session["id"]) == 0


async def test_stream_chat_rejects_blank_text(
    client: httpx.AsyncClient, auth_user: dict, auth_headers: dict
) -> None:
    """纯空白提问由校验层拦截为 422。"""
    session = _new_session(auth_user["id"])

    resp = await client.post(
        f"/api/sessions/{session['id']}/stream-chat",
        headers=auth_headers,
        json={"request_text": "   "},
    )

    assert resp.status_code == 422
    assert resp.json()["code"] == 422
