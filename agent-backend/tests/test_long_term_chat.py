"""流式对话接入长期记忆：意图判断、跳过 RAG、异步触发画像更新。"""

import httpx

from app.db import message_repo, session_repo
from app.services import chat_service


class _FakeChain:
    """模拟 LangChain 链路：记录入参并逐段产出回复。"""

    def __init__(self, chunks: list[str], captured: list[dict] | None = None) -> None:
        self._chunks = chunks
        self._captured = captured

    async def astream(self, context: dict):
        if self._captured is not None:
            self._captured.append(context)
        for chunk in self._chunks:
            yield chunk


def _new_session(user_id: int) -> dict:
    return session_repo.insert(
        {"user_id": user_id, "title": "长期记忆会话", "session_mode": 0}
    )


def _patch_chain(monkeypatch, chain: object) -> None:
    monkeypatch.setattr(
        chat_service.prompt_layer, "build_chat_chain", lambda *args, **kwargs: chain
    )


async def test_profile_intent_skips_rag(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    monkeypatch,
) -> None:
    """命中画像写入意图时不调用知识库检索，问题原样进入链路。"""
    session = _new_session(auth_user["id"])
    retrieval_calls: list[tuple] = []

    from app.rag import retriever

    monkeypatch.setattr(
        retriever,
        "search_similar_chunks",
        lambda *args, **kwargs: retrieval_calls.append(args) or [],
    )
    monkeypatch.setattr(
        chat_service.LongTermMemory,
        "should_write",
        lambda self, text, user_id=None: True,
    )
    captured: list[dict] = []
    _patch_chain(monkeypatch, _FakeChain(["好的"], captured))

    resp = await client.post(
        f"/api/sessions/{session['id']}/stream-chat",
        headers=auth_headers,
        json={"request_text": "我想转行做后端开发"},
    )

    assert resp.status_code == 200, resp.text
    assert retrieval_calls == []
    assert captured[0]["input"] == "我想转行做后端开发"
    assert '"sources": []' in resp.text


async def test_profile_intent_submits_async_update(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    monkeypatch,
    stub_long_term_memory: dict,
) -> None:
    """流成功后用最近历史 + 本轮回复触发后台画像更新。"""
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
    monkeypatch.setattr(
        chat_service.LongTermMemory,
        "should_write",
        lambda self, text, user_id=None: True,
    )
    _patch_chain(monkeypatch, _FakeChain(["建议", "从基础开始"]))

    resp = await client.post(
        f"/api/sessions/{session['id']}/stream-chat",
        headers=auth_headers,
        json={"request_text": "我想转行做后端开发"},
    )

    assert resp.status_code == 200, resp.text
    calls = stub_long_term_memory["submit"]
    assert len(calls) == 1
    call = calls[0]
    assert call["user_id"] == auth_user["id"]
    assert call["request_text"] == "我想转行做后端开发"
    assert [item["content"] for item in call["context"]] == [
        "历史问题",
        "历史回答",
        "建议从基础开始",
    ]
    assert call["context"][-1]["role"] == "assistant"


async def test_non_profile_message_does_not_update_profile(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    monkeypatch,
    stub_long_term_memory: dict,
) -> None:
    """普通提问不命中意图，不触发画像更新。"""
    session = _new_session(auth_user["id"])
    _patch_chain(monkeypatch, _FakeChain(["回答"]))

    resp = await client.post(
        f"/api/sessions/{session['id']}/stream-chat",
        headers=auth_headers,
        json={"request_text": "解释一下什么是索引"},
    )

    assert resp.status_code == 200, resp.text
    assert stub_long_term_memory["submit"] == []
