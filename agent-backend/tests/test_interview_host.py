"""面试主考官两阶段流程测试。

覆盖：总控直接分发、会话模式校验、简历资源与切片读取、变量提取、
最新输入优先（本轮表述 / 资料与简历按时间取新）、待确认背景落库、
确认接口创建入口消息与 Interview、提示词重新渲染、同一 run 只确认一次。
模型与提示词模板用替身。
"""

import json
import time
import uuid

import httpx
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app.agent.agents import interview_host
from app.db import (
    interview_repo,
    knowledge_chunk_repo,
    message_repo,
    resource_repo,
    session_repo,
    user_profile_repo,
    workflow_run_repo,
)
from app.db.models import KnowledgeChunk
from app.db.session import SessionLocal
from app.services import interview_host_workflow
from app.services.orchestrator_service import (
    INTERVIEW_HOST_AGENT_NAME,
    WORKFLOW_ROUTE_RULES,
    OrchestratorService,
)

BASE = "/api/agent/tasks/start"
CONFIRM = "/api/interviews/confirm"

EXTRACTED = {
    "target_job": "后端开发工程师",
    "target_level": "P6",
    "years_experience": 3,
    "target_skills": ["Python", "MySQL"],
    "project_experience": "负责订单系统开发。",
    "weak_topics": ["分布式事务"],
    "opening_question": "请介绍你最近负责的那个订单系统项目。",
}
EXTRACTION_JSON = json.dumps(EXTRACTED, ensure_ascii=False)

STATED = {
    "target_job": "前端开发工程师",
    "target_level": "P7",
    "years_experience": 5,
    "target_skills": ["Vue", "TypeScript"],
    "weak_topics": ["性能优化"],
}
STATED_JSON = json.dumps(
    {**EXTRACTED, "user_stated": STATED}, ensure_ascii=False
)

EXPECTED_BACKGROUND = {
    "target_job": "后端开发工程师",
    "target_level": "P6",
    "years_experience": "3 年",
    "target_skills": "Python、MySQL",
    "project_experience": "负责订单系统开发。",
    "weak_topics": "分布式事务",
    "opening_question": "请介绍你最近负责的那个订单系统项目。",
}

# 资料写入时间需要相对简历上传时间可控：未来一秒即「资料更新」，过去一秒反之
PROFILE_NEWER = int(time.time()) + 3600
PROFILE_OLDER = int(time.time()) - 3600

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


async def _prepare(
    client: httpx.AsyncClient,
    headers: dict,
    user_id: int,
    monkeypatch,
    request_text: str = "开始面试",
) -> tuple[dict, dict]:
    """跑完第一阶段，返回 (会话, 响应 data)。"""
    _patch_model(monkeypatch)
    session = _interview_session(user_id)
    _add_resume(user_id, ["项目经历：订单系统，技术栈 Python、MySQL。"])
    resp = await client.post(
        BASE,
        headers=headers,
        json={
            "agent_name": INTERVIEW_HOST_AGENT_NAME,
            "session_id": session["id"],
            "request_text": request_text,
        },
    )
    assert resp.status_code == 200, resp.text
    return session, resp.json()["data"]


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


async def test_prepare_returns_pending_background(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    monkeypatch,
) -> None:
    """第一阶段只返回待确认背景，并把 background 写入 workflow_runs。"""
    _patch_model(monkeypatch)
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
    assert data["status"] == "pending_confirmation"
    assert data["run_id"]
    assert data["resume"]["file_name"] == "resume.pdf"
    assert data["resume"]["doc_category"] == "resume"
    assert data["background"] == EXPECTED_BACKGROUND
    assert "prompt" not in data
    assert "variables" not in data

    run = workflow_run_repo.get_for_user(data["run_id"], auth_user["id"])
    assert run["workflow_type"] == "interview_prepare"
    assert run["status"] == "pending_confirmation"
    assert run["state_json"]["background"] == EXPECTED_BACKGROUND
    assert run["state_json"]["request_text"] == "开始面试"


async def test_user_profile_overrides_resume_extraction(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    monkeypatch,
) -> None:
    """资料晚于简历上传时，岗位 / 职级 / 技能 / 薄弱点 / 年限优先，开场问题仍取简历。"""
    _patch_model(monkeypatch)
    session = _interview_session(auth_user["id"])
    _add_resume(auth_user["id"], ["项目经历：订单系统，技术栈 Python、MySQL。"])
    user_profile_repo.insert(
        auth_user["id"],
        {
            "target_job": "前端开发工程师",
            "years_experience": 5,
            "target_level": "P7",
            "target_skills": ["Vue", "TypeScript"],
            "weak_topics": ["性能优化"],
            "updated_at": PROFILE_NEWER,
        },
    )

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
    assert data["background"] == {
        "target_job": "前端开发工程师",
        "target_level": "P7",
        "years_experience": "5 年",
        "target_skills": "Vue、TypeScript",
        "project_experience": EXTRACTED["project_experience"],
        "weak_topics": "性能优化",
        "opening_question": EXTRACTED["opening_question"],
    }


async def test_empty_profile_fields_fall_back_to_resume(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    monkeypatch,
) -> None:
    """资料更新更晚，但未填 / 空值的字段仍回退简历提取结果。"""
    _patch_model(monkeypatch)
    session = _interview_session(auth_user["id"])
    _add_resume(auth_user["id"], ["教育背景：本科；项目经历：订单系统。"])
    user_profile_repo.insert(
        auth_user["id"],
        {
            "target_job": "前端开发工程师",
            "target_skills": [],
            "updated_at": PROFILE_NEWER,
        },
    )

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
    background = resp.json()["data"]["background"]
    assert background["target_job"] == "前端开发工程师"
    assert background["target_level"] == EXTRACTED["target_level"]
    assert background["years_experience"] == "3 年"
    assert background["target_skills"] == "Python、MySQL"
    assert background["weak_topics"] == "分布式事务"


async def test_resume_newer_than_profile_wins(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    monkeypatch,
) -> None:
    """简历上传晚于资料写入时，冲突字段以简历为准。"""
    _patch_model(monkeypatch)
    session = _interview_session(auth_user["id"])
    _add_resume(auth_user["id"], ["项目经历：订单系统，技术栈 Python、MySQL。"])
    user_profile_repo.insert(
        auth_user["id"],
        {
            "target_job": "前端开发工程师",
            "years_experience": 5,
            "target_level": "P7",
            "target_skills": ["Vue", "TypeScript"],
            "weak_topics": ["性能优化"],
            "updated_at": PROFILE_OLDER,
        },
    )

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
    assert resp.json()["data"]["background"] == EXPECTED_BACKGROUND


async def test_chat_statement_overrides_profile_and_resume(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    monkeypatch,
) -> None:
    """本轮明确表述优先级最高：覆盖更晚写入的资料与简历，年限同步更新。"""
    _patch_model(monkeypatch, STATED_JSON)
    session = _interview_session(auth_user["id"])
    _add_resume(auth_user["id"], ["项目经历：订单系统，技术栈 Python、MySQL。"])
    user_profile_repo.insert(
        auth_user["id"],
        {
            "target_job": "全栈开发工程师",
            "years_experience": 8,
            "target_level": "P8",
            "target_skills": ["Java"],
            "weak_topics": ["架构设计"],
            "updated_at": PROFILE_NEWER,
        },
    )

    resp = await client.post(
        BASE,
        headers=auth_headers,
        json={
            "agent_name": INTERVIEW_HOST_AGENT_NAME,
            "session_id": session["id"],
            "request_text": "我想面前端，5 年经验，P7，重点考察性能优化",
        },
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["background"] == {
        "target_job": STATED["target_job"],
        "target_level": STATED["target_level"],
        "years_experience": "5 年",
        "target_skills": "Vue、TypeScript",
        "project_experience": EXTRACTED["project_experience"],
        "weak_topics": STATED["weak_topics"][0],
        "opening_question": EXTRACTED["opening_question"],
    }


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


async def test_confirm_creates_interview_message_and_prompt(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    monkeypatch,
) -> None:
    """确认后创建入口消息与 Interview，并按编辑后的背景重新渲染提示词。"""
    session, prepared = await _prepare(
        client, auth_headers, auth_user["id"], monkeypatch
    )
    _patch_template(monkeypatch)
    background = {
        **prepared["background"],
        "target_job": "前端开发工程师",
        "target_level": "P7",
        "years_experience": "5 年",
        "target_skills": "Vue、TypeScript",
        "project_experience": "负责电商前端重构。",
        "weak_topics": "性能优化",
        "opening_question": "请介绍你负责的前端项目。",
    }

    resp = await client.post(
        CONFIRM,
        headers=auth_headers,
        json={"run_id": prepared["run_id"], "background": background},
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["status"] == "confirmed"
    assert data["run_id"] == prepared["run_id"]
    assert data["session_id"] == session["id"]
    assert data["interview_id"]
    assert data["message_id"]

    interview = interview_repo.get(data["interview_id"])
    assert interview["user_id"] == auth_user["id"]
    assert interview["session_id"] == session["id"]
    assert interview["message_id"] == data["message_id"]
    assert interview["qa_object"] == []
    assert interview["status"] == 0
    assert "岗位：前端开发工程师" in interview["interview_host_prompt"]
    assert "职级：P7" in interview["interview_host_prompt"]
    assert "年限：5 年" in interview["interview_host_prompt"]
    assert "技能：Vue、TypeScript" in interview["interview_host_prompt"]
    assert "薄弱点：性能优化" in interview["interview_host_prompt"]
    assert "后端开发工程师" not in interview["interview_host_prompt"]

    message = message_repo.get(data["message_id"])
    assert message["user_id"] == auth_user["id"]
    assert message["session_id"] == session["id"]
    assert message["select_mode"] == 4
    assert message["request_id"] == f"{prepared['run_id']}:interview"
    assert message["request_text"] == "开始面试"
    assert message["response_text"] == background["opening_question"]
    assert message["status"] == 1
    assert message["interview_id"] == data["interview_id"]

    run = workflow_run_repo.get_for_user(prepared["run_id"], auth_user["id"])
    assert run["status"] == "confirmed"
    assert run["state_json"]["confirmed_background"] == background
    assert run["state_json"]["interview_id"] == data["interview_id"]
    assert run["state_json"]["message_id"] == data["message_id"]

    detail = await client.get(
        f"/api/interviews/{data['interview_id']}", headers=auth_headers
    )
    assert detail.status_code == 200, detail.text
    assert "岗位：前端开发工程师" in detail.json()["data"]["interview_host_prompt"]


async def test_confirm_only_once(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    monkeypatch,
) -> None:
    """同一个 run_id 第二次确认返回 409，不重复创建面试。"""
    _, prepared = await _prepare(client, auth_headers, auth_user["id"], monkeypatch)
    _patch_template(monkeypatch)
    payload = {
        "run_id": prepared["run_id"],
        "background": prepared["background"],
    }

    first = await client.post(CONFIRM, headers=auth_headers, json=payload)
    assert first.status_code == 200, first.text
    second = await client.post(CONFIRM, headers=auth_headers, json=payload)
    assert second.status_code == 409

    run = workflow_run_repo.get_for_user(prepared["run_id"], auth_user["id"])
    assert run["status"] == "confirmed"
    assert run["state_json"]["interview_id"] == first.json()["data"]["interview_id"]


async def test_confirm_rejects_foreign_run(
    client: httpx.AsyncClient,
    auth_headers: dict,
    other_auth: tuple[dict, dict],
    monkeypatch,
) -> None:
    """不能确认别人的面试准备运行。"""
    other_user, other_headers = other_auth
    _, prepared = await _prepare(
        client, other_headers, other_user["id"], monkeypatch
    )

    resp = await client.post(
        CONFIRM,
        headers=auth_headers,
        json={"run_id": prepared["run_id"], "background": prepared["background"]},
    )

    assert resp.status_code == 404


async def test_confirm_requires_existing_run(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    """未知 run_id → 404。"""
    resp = await client.post(
        CONFIRM,
        headers=auth_headers,
        json={
            "run_id": str(uuid.uuid4()),
            "background": EXPECTED_BACKGROUND,
        },
    )

    assert resp.status_code == 404
