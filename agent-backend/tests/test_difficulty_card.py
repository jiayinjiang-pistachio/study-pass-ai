"""难点知识卡工作流测试。

覆盖：总控直接分发、卡片原料整理、绘图提示词确定性拼接、图片落库与会话消息、
历史消息按 resource_id 续签 URL、会话越权、出图配置缺失（503）。
模型 / Seedream / MinIO 均用替身，不触达外部服务。
"""

import uuid

import httpx
from sqlalchemy import select

from app.agent.agents import difficulty_learner
from app.db import message_repo, resource_repo, session_repo, workflow_run_repo
from app.db.models import WorkflowRun
from app.db.session import SessionLocal
from app.services import difficulty_card_workflow
from app.services.orchestrator_service import (
    DIFFICULTY_AGENT_NAME,
    WORKFLOW_ROUTE_RULES,
    OrchestratorService,
)

BASE = "/api/agent/tasks/start"

CARD = {
    "title": "Python GIL",
    "topic": "Python 并发",
    "summary": "GIL 让同一进程内多线程无法并行执行 Python 字节码。",
    "points": [
        {"title": "本质", "tip": "全局解释器锁一次只允许一个线程执行字节码。"},
        {"title": "影响", "tip": "CPU 密集任务用多进程，IO 密集任务多线程仍有效。"},
    ],
}


def _patch_pipeline(monkeypatch) -> list[int]:
    """替身：卡片原料固定，出图返回假字节，落库返回真实 resources 记录。"""
    calls: list[int] = []

    def fake_prepare(self, _user_id, _request_text, _qa_context=""):
        return dict(CARD)

    def fake_save(user_id, data, *, file_name="knowledge-card"):
        calls.append(len(data))
        resource = resource_repo.insert(
            {
                "user_id": user_id,
                "resource_type": 1,
                "file_name": f"{file_name}.png",
                "file_hash": uuid.uuid4().hex,
                "storage_path": f"minio:/bucket/users/{user_id}/{uuid.uuid4().hex}.png",
                "expire_time": None,
            }
        )
        return {"resource": resource, "created": True}

    monkeypatch.setattr(
        difficulty_learner.DifficultyLearnerAgent, "prepare_card", fake_prepare
    )
    monkeypatch.setattr(
        difficulty_card_workflow.seedream_service,
        "generate_image",
        lambda _prompt: b"\x89PNG\r\n\x1a\nfake",
    )
    monkeypatch.setattr(
        difficulty_card_workflow.upload_service_minio,
        "save_generated_image",
        fake_save,
    )
    monkeypatch.setattr(
        difficulty_card_workflow.minio_client,
        "presigned_url_for_storage_path",
        lambda _path: "http://minio.local/card.png",
    )
    return calls


def _new_session(user_id: int) -> dict:
    return session_repo.insert(
        {"user_id": user_id, "title": "学习会话", "session_mode": 0}
    )


def test_difficulty_learner_routes_directly() -> None:
    """difficulty_learner 命中即分发，不经过关键词 / 语义判断。"""
    rule = OrchestratorService().route(DIFFICULTY_AGENT_NAME, "你好")

    assert rule is WORKFLOW_ROUTE_RULES[DIFFICULTY_AGENT_NAME]
    assert rule.direct is True


def test_image_prompt_is_deterministic() -> None:
    """绘图提示词由卡片字段确定性拼接，并包含竖版信息图约束。"""
    prompt = difficulty_learner.build_image_prompt(CARD)

    assert CARD["title"] in prompt
    assert CARD["summary"] in prompt
    assert CARD["points"][0]["tip"] in prompt
    assert "竖版" in prompt
    assert prompt == difficulty_learner.build_image_prompt(CARD)


async def test_generate_card_creates_image_message(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    monkeypatch,
) -> None:
    """出图成功后写入带 resource_id 的会话消息，并把 run 置为 completed。"""
    calls = _patch_pipeline(monkeypatch)
    session = _new_session(auth_user["id"])

    resp = await client.post(
        BASE,
        headers=auth_headers,
        json={
            "agent_name": DIFFICULTY_AGENT_NAME,
            "session_id": session["id"],
            "request_text": "讲讲 Python GIL",
        },
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["route"] == "workflow"
    assert data["workflow_type"] == "difficulty_card"
    assert data["status"] == "completed"
    assert data["title"] == CARD["title"]
    assert data["image_url"] == "http://minio.local/card.png"
    assert calls

    run = workflow_run_repo.get_for_user(data["run_id"], auth_user["id"])
    assert run["status"] == "completed"
    assert run["state_json"]["resource_id"] == data["resource_id"]

    messages = message_repo.list_by_session(session["id"], 0, 20)
    card_messages = [row for row in messages if row.get("response_segments")]
    assert len(card_messages) == 1
    assert card_messages[0]["request_id"] == f"{data['run_id']}:card"
    assert (
        card_messages[0]["response_segments"][0]["resource_id"] == data["resource_id"]
    )


async def test_message_history_renews_image_url(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    monkeypatch,
) -> None:
    """历史消息只存 resource_id，读取时重新预签名 URL。"""
    _patch_pipeline(monkeypatch)
    session = _new_session(auth_user["id"])
    resp = await client.post(
        BASE,
        headers=auth_headers,
        json={
            "agent_name": DIFFICULTY_AGENT_NAME,
            "session_id": session["id"],
            "request_text": "讲讲 Python GIL",
        },
    )
    assert resp.status_code == 200, resp.text

    listed = await client.get(
        f"/api/sessions/{session['id']}/messages?page=1&page_size=20",
        headers=auth_headers,
    )
    assert listed.status_code == 200, listed.text
    segment = listed.json()["data"]["items"][0]["response_segments"][0]
    assert segment["type"] == "image"
    assert segment["url"] == "http://minio.local/card.png"


async def test_generate_card_rejects_foreign_session(
    client: httpx.AsyncClient,
    auth_headers: dict,
    other_auth: tuple[dict, dict],
    monkeypatch,
) -> None:
    """会话不属于当前用户 → 404，不触达模型与出图。"""
    _patch_pipeline(monkeypatch)
    other_user, _ = other_auth
    other = session_repo.insert(
        {"user_id": other_user["id"], "title": "他人会话", "session_mode": 0}
    )

    resp = await client.post(
        BASE,
        headers=auth_headers,
        json={
            "agent_name": DIFFICULTY_AGENT_NAME,
            "session_id": other["id"],
            "request_text": "讲讲 Python GIL",
        },
    )

    assert resp.status_code == 404, resp.text


async def test_missing_seedream_key_returns_503(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    monkeypatch,
) -> None:
    """出图配置缺失 → 503，且 run 记录置为 failed。"""
    _patch_pipeline(monkeypatch)
    monkeypatch.setattr(
        difficulty_card_workflow.seedream_service,
        "generate_image",
        lambda _prompt: (_ for _ in ()).throw(
            RuntimeError("环境变量 SEEDREAM_API_KEY 未配置")
        ),
    )
    session = _new_session(auth_user["id"])

    resp = await client.post(
        BASE,
        headers=auth_headers,
        json={
            "agent_name": DIFFICULTY_AGENT_NAME,
            "session_id": session["id"],
            "request_text": "讲讲 Python GIL",
        },
    )

    assert resp.status_code == 503, resp.text
    with SessionLocal() as db:
        runs = db.scalars(
            select(WorkflowRun).where(WorkflowRun.session_id == session["id"])
        ).all()
    assert len(runs) == 1
    assert runs[0].status == "failed"
    assert "SEEDREAM_API_KEY" in runs[0].error_message
