"""RAG 对话链路测试。

覆盖：检索意图判断、片段格式化、按需注入、done 来源下发、
reference_sources 只存索引，以及历史消息回查 / 片段删除兜底。
检索与模型均替换为桩，不依赖 DashScope / Qdrant / 大模型。
"""

import json
import uuid

import httpx
import pytest

from app.db import message_repo, session_repo
from app.db.models import KnowledgeChunk, Resource
from app.db.session import SessionLocal
from app.rag import context as rag_context
from app.services import chat_service
from app.services.ai import prompt_layer


class _FakeChain:
    """模拟流式链路：记录上下文并按顺序产出增量文本。"""

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
        {"user_id": user_id, "title": "RAG 会话", "session_mode": 0}
    )


def _new_resource(user_id: int, file_name: str = "resume.pdf") -> int:
    with SessionLocal() as session:
        resource = Resource(
            resource_type=0,
            doc_category="resume",
            file_name=file_name,
            file_hash=f"hash-{uuid.uuid4().hex}",
            storage_path="",
            user_id=user_id,
        )
        session.add(resource)
        session.commit()
        return resource.id


def _new_chunk(resource_id: int, text: str, chunk_index: int = 0) -> str:
    vector_id = str(uuid.uuid4())
    with SessionLocal() as session:
        session.add(
            KnowledgeChunk(
                vector_id=vector_id,
                resource_id=resource_id,
                chunk_index=chunk_index,
                text=text,
                char_count=len(text),
            )
        )
        session.commit()
    return vector_id


def _done_payload(body: str) -> dict:
    return json.loads(body.split("event: done\ndata: ")[1].split("\n\n")[0])


# ---- 意图判断 ----

@pytest.mark.parametrize(
    "text",
    ["", "   ", "好的", "嗯嗯", "谢谢", "继续", "下一步", "hello", "OK", "好的，谢谢"],
)
def test_should_retrieve_skips_noise(text: str) -> None:
    """空输入、极短输入、确认 / 礼貌 / 推进语不检索。"""
    assert rag_context.should_retrieve(text) is False


@pytest.mark.parametrize(
    "text",
    ["什么是 Python 闭包", "帮我优化简历里的项目经历", "Redis 缓存穿透怎么解决"],
)
def test_should_retrieve_accepts_questions(text: str) -> None:
    """包含实质内容的提问照常检索。"""
    assert rag_context.should_retrieve(text) is True


def test_format_retrieved_chunks() -> None:
    """参考文本包含来源、编号、相似度与正文。"""
    text = rag_context.format_retrieved_chunks(
        [
            {
                "file_name": "resume.pdf",
                "chunk_index": 2,
                "score": 0.834,
                "text": "项目经历：使用 FastAPI 搭建后端。",
            }
        ]
    )
    assert "【知识库参考资料】" in text
    assert "[1]" in text
    assert "resume.pdf" in text
    assert "0.83" in text
    assert "FastAPI" in text
    assert rag_context.format_retrieved_chunks([]) == ""


def test_build_rag_system_prompt_only_adds_rules() -> None:
    """RAG 提示词只补充回答规则，不重写基础人设。"""
    rules = prompt_layer.build_rag_system_prompt()
    assert "[1]" in rules
    assert "参考资料" in rules
    assert "学面通 AI" not in rules


# ---- 流式对话 ----

async def test_stream_chat_injects_and_returns_sources(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    monkeypatch,
) -> None:
    """命中资料：注入本轮问题、done 返回完整 sources、落库只存 chunk_id/score。"""
    session = _new_session(auth_user["id"])
    resource_id = _new_resource(auth_user["id"])
    chunk_text = "项目经历：使用 FastAPI 搭建后端接口。"
    vector_id = _new_chunk(resource_id, chunk_text)

    hit = {
        "vector_id": vector_id,
        "resource_id": resource_id,
        "file_name": "resume.pdf",
        "doc_category": "resume",
        "chunk_index": 0,
        "score": 0.87,
        "text": chunk_text,
    }
    monkeypatch.setattr(
        "app.rag.retriever.search_similar_chunks", lambda *args, **kwargs: [hit]
    )

    captured: list[dict] = []
    monkeypatch.setattr(
        chat_service.prompt_layer,
        "build_chat_chain",
        lambda *args, **kwargs: _FakeChain(["基于资料", "回答"], captured),
    )

    question = "我的项目用了什么后端框架？"
    resp = await client.post(
        f"/api/sessions/{session['id']}/stream-chat",
        headers=auth_headers,
        json={"request_text": question},
    )
    assert resp.status_code == 200, resp.text

    # 注入：参考文本在问题之前
    assert len(captured) == 1
    assert "【知识库参考资料】" in captured[0]["input"]
    assert captured[0]["input"].endswith(question)

    # done 事件带完整来源
    done = _done_payload(resp.text)
    assert done["sources"] == [
        {
            "chunk_id": vector_id,
            "resource_id": resource_id,
            "chunk_index": 0,
            "file_name": "resume.pdf",
            "score": 0.87,
            "text": chunk_text,
        }
    ]

    # 落库只保留索引，不重复保存知识块全文
    latest = next(
        item
        for item in message_repo.list_all_by_session(session["id"])
        if item["request_text"] == question
    )
    assert latest["reference_sources"] == [{"chunk_id": vector_id, "score": 0.87}]
    assert all(
        set(ref) == {"chunk_id", "score"} for ref in latest["reference_sources"]
    )


async def test_stream_chat_skips_retrieval_for_filler(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    monkeypatch,
) -> None:
    """确认语不触发检索，done 的 sources 为空。"""
    session = _new_session(auth_user["id"])

    def _boom(*args, **kwargs):
        raise AssertionError("寒暄语不应触发检索")

    monkeypatch.setattr("app.rag.retriever.search_similar_chunks", _boom)
    monkeypatch.setattr(
        chat_service.prompt_layer,
        "build_chat_chain",
        lambda *args, **kwargs: _FakeChain(["好的"]),
    )

    resp = await client.post(
        f"/api/sessions/{session['id']}/stream-chat",
        headers=auth_headers,
        json={"request_text": "好的"},
    )
    assert resp.status_code == 200, resp.text
    assert _done_payload(resp.text)["sources"] == []


# ---- 历史回显 ----

async def test_history_messages_rebuild_sources(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
) -> None:
    """历史消息按 reference_sources 回查原文与文件名。"""
    session = _new_session(auth_user["id"])
    resource_id = _new_resource(auth_user["id"])
    vector_id = _new_chunk(resource_id, "历史片段原文", chunk_index=3)

    message_repo.insert(
        {
            "user_id": auth_user["id"],
            "session_id": session["id"],
            "select_mode": 0,
            "request_id": f"req-{uuid.uuid4().hex}",
            "request_text": "历史提问",
            "response_text": "历史回答",
            "status": 1,
            "reference_sources": [{"chunk_id": vector_id, "score": 0.9}],
        }
    )

    resp = await client.get(
        f"/api/sessions/{session['id']}/messages", headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    item = resp.json()["data"]["items"][0]
    assert item["sources"] == [
        {
            "chunk_id": vector_id,
            "resource_id": resource_id,
            "chunk_index": 3,
            "file_name": "resume.pdf",
            "score": 0.9,
            "text": "历史片段原文",
        }
    ]


async def test_history_message_marks_deleted_source(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
) -> None:
    """知识块已删除：保留来源条目并返回提示文案。"""
    session = _new_session(auth_user["id"])
    message_repo.insert(
        {
            "user_id": auth_user["id"],
            "session_id": session["id"],
            "select_mode": 0,
            "request_id": f"req-{uuid.uuid4().hex}",
            "request_text": "历史提问",
            "response_text": "历史回答",
            "status": 1,
            "reference_sources": [{"chunk_id": "missing-chunk", "score": 0.5}],
        }
    )

    resp = await client.get(
        f"/api/sessions/{session['id']}/messages", headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    source = resp.json()["data"]["items"][0]["sources"][0]
    assert source == {
        "chunk_id": "missing-chunk",
        "resource_id": None,
        "chunk_index": None,
        "file_name": None,
        "score": 0.5,
        "text": "该参考片段已被删除",
    }
