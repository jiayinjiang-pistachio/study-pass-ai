"""面试主考官面试前准备测试。

覆盖：总控直接分发、会话模式校验、简历资源与切片读取、变量提取、
提示词注入、开场问题返回与用户隔离。模型与提示词模板用替身。
"""

import json
import uuid

import httpx
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app.agent.agents import interview_host
from app.db import knowledge_chunk_repo, resource_repo, session_repo
from app.db.models import KnowledgeChunk
from app.db.session import SessionLocal
from app.services import interview_host_workflow
from app.services.orchestrator_service import (
    INTERVIEW_HOST_AGENT_NAME,
    WORKFLOW_ROUTE_RULES,
    OrchestratorService,
)

BASE = "/api/agent/tasks/start"

EXTRACTED = {
    "target_job": "后端开发工程师",
    "target_level": "P6",
    "target_skills": ["Python", "MySQL"],
    "weak_topics": ["分布式事务"],
    "opening_question": "请介绍你最近负责的那个订单系统项目。",
}
EXTRACTION_JSON = json.dumps(EXTRACTED, ensure_ascii=False)

PROMPT_TEMPLATE = (
    "岗位：{target_job}；职级：{target_level}；年限：{years_experience}；"
    "技能：{target_skills}；薄弱点：{weak_topics}。"
)


def _patch_model(monkeypatch, content: str = EXTRACTION_JSON) -> None:
    monkeypatch.setattr(
        interview_host,
        "get_chat_model",
        lambda: RunnableLambda(lambda _: AIMessage(content=content)),
    )


def _patch_template(monkeypatch) -> None:
    """只保留占位符与画像注入值，避免依赖数据库中的模板版本。"""
    monkeypatch.setattr(
        interview_host_workflow.prompt_template_service,
        "get_combined_template",
        lambda *args, **kwargs: {
            "final_template": PROMPT_TEMPLATE,
            "injected_variables": {"years_experience": "3 年"},
        },
    )


def _interview_session(user_id: int, session_mode: int = 1) -> dict:
    return session_repo.insert(
        {"user_id": user_id, "title": "面试会话", "session_mode": session_mode}
    )


def _add_resume(user_id: int, chunks: list[str] | None = None) -> dict:
    resource = resource_repo.insert(
        {
            "user_id": user_id,
            "resource_type": 0,
            "doc_category": "resume",
            "file_name": "resume.pdf",
            "file_hash": uuid.uuid4().hex,
            "storage_path": "minio:/bucket/resume.pdf",
        }
    )
    for index, text in enumerate(chunks or []):
        _add_chunk(resource["id"], index, text)
    return resource


def _add_chunk(resource_id: int, index: int, text: str) -> None:
    with SessionLocal() as session:
        session.add(
            KnowledgeChunk(
                vector_id=str(uuid.uuid4()),
                resource_id=resource_id,
                chunk_index=index,
                text=text,
                char_count=len(text),
            )
        )
        session.commit()


def test_interview_host_routes_directly() -> None:
    """interview_host 命中即分发，不经过关键词 / 语义判断。"""
    rule = OrchestratorService().route(INTERVIEW_HOST_AGENT_NAME, "你好")

    assert rule is WORKFLOW_ROUTE_RULES[INTERVIEW_HOST_AGENT_NAME]
    assert rule.direct is True


def test_resume_chunks_joined_in_order(auth_user: dict) -> None:
    """简历正文按 chunk_index 升序拼接，与插入顺序无关。"""
    resource = _add_resume(auth_user["id"])
    for index, text in ((2, "第三段"), (0, "第一段"), (1, "第二段")):
        _add_chunk(resource["id"], index, text)

    assert (
        knowledge_chunk_repo.get_text_by_resource(resource["id"])
        == "第一段\n第二段\n第三段"
    )


async def test_prepare_returns_prompt_and_opening_question(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    monkeypatch,
) -> None:
    """成功链路：简历变量覆盖画像，年限沿用画像，开场问题独立返回。"""
    _patch_model(monkeypatch)
    _patch_template(monkeypatch)
    session = _interview_session(auth_user["id"])
    _add_resume(auth_user["id"], ["教育背景：本科。", "项目经历：订单系统。"])

    resp = await client.post(
        BASE,
        headers=auth_headers,
        json={
            "agent_name": INTERVIEW_HOST_AGENT_NAME,
            "session_id": session["id"],
            "request_text": "开始面试",
        },
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["route"] == "workflow"
    assert data["workflow_type"] == "interview_prepare"
    assert data["session_id"] == session["id"]
    assert data["resume"]["file_name"] == "resume.pdf"
    assert data["resume"]["doc_category"] == "resume"
    assert data["variables"] == EXTRACTED
    assert data["opening_question"] == EXTRACTED["opening_question"]
    assert "岗位：后端开发工程师" in data["prompt"]
    assert "职级：P6" in data["prompt"]
    assert "年限：3 年" in data["prompt"]
    assert "技能：Python、MySQL" in data["prompt"]
    assert "薄弱点：分布式事务" in data["prompt"]
    assert "{target_job}" not in data["prompt"]


async def test_prepare_requires_interview_session(
    client: httpx.AsyncClient, auth_user: dict, auth_headers: dict
) -> None:
    """非面试模式会话 → 400。"""
    session = _interview_session(auth_user["id"], session_mode=0)

    resp = await client.post(
        BASE,
        headers=auth_headers,
        json={
            "agent_name": INTERVIEW_HOST_AGENT_NAME,
            "session_id": session["id"],
            "request_text": "开始面试",
        },
    )

    assert resp.status_code == 400


async def test_prepare_rejects_foreign_session(
    client: httpx.AsyncClient,
    auth_headers: dict,
    other_auth: tuple[dict, dict],
) -> None:
    """不能使用别人的面试会话。"""
    other_user, _ = other_auth
    session = _interview_session(other_user["id"])

    resp = await client.post(
        BASE,
        headers=auth_headers,
        json={
            "agent_name": INTERVIEW_HOST_AGENT_NAME,
            "session_id": session["id"],
            "request_text": "开始面试",
        },
    )

    assert resp.status_code == 404


async def test_prepare_requires_resume(
    client: httpx.AsyncClient, auth_user: dict, auth_headers: dict
) -> None:
    """没有简历资源 → 404。"""
    session = _interview_session(auth_user["id"])

    resp = await client.post(
        BASE,
        headers=auth_headers,
        json={
            "agent_name": INTERVIEW_HOST_AGENT_NAME,
            "session_id": session["id"],
            "request_text": "开始面试",
        },
    )

    assert resp.status_code == 404


async def test_prepare_rejects_unparsed_resume(
    client: httpx.AsyncClient, auth_user: dict, auth_headers: dict
) -> None:
    """简历资源存在但没有切片（尚未解析）→ 409。"""
    session = _interview_session(auth_user["id"])
    _add_resume(auth_user["id"])

    resp = await client.post(
        BASE,
        headers=auth_headers,
        json={
            "agent_name": INTERVIEW_HOST_AGENT_NAME,
            "session_id": session["id"],
            "request_text": "开始面试",
        },
    )

    assert resp.status_code == 409
