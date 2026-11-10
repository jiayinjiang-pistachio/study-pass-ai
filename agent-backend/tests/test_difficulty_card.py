"""难点知识卡工作流测试。

覆盖：总控直接分发、卡片原料整理、绘图 / 播客提示词确定性拼接、图片与音频
落库、会话消息附件段、历史消息按 resource_id 续签 URL、音频软失败、会话越权、
出图配置缺失（503）。模型 / Seedream / 播客 TTS / MinIO 均用替身，不触达外部服务。
"""

import json
import struct
import uuid

import httpx
from sqlalchemy import select

from app.agent.agents import difficulty_learner
from app.agent.registry import DIFFICULTY_AGENT, get_capability
from app.db import message_repo, resource_repo, session_repo, workflow_run_repo
from app.db.models import WorkflowRun
from app.db.session import SessionLocal
from app.services import difficulty_card_workflow, podcast_service

BASE = "/api/agent/chat"

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
    """替身：卡片原料固定，出图 / 出音频返回假字节，落库返回真实 resources 记录。"""
    calls: list[int] = []

    def fake_prepare(self, _user_id, _request_text, _qa_context=""):
        return dict(CARD)

    def _fake_save(user_id, data, *, file_name, resource_type, suffix):
        calls.append(len(data))
        resource = resource_repo.insert(
            {
                "user_id": user_id,
                "resource_type": resource_type,
                "file_name": f"{file_name}{suffix}",
                "file_hash": uuid.uuid4().hex,
                "storage_path": (
                    f"minio:/bucket/users/{user_id}/{uuid.uuid4().hex}{suffix}"
                ),
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
        difficulty_card_workflow.podcast_service,
        "generate_podcast",
        lambda _topic: b"ID3\x03\x00\x00\x00fake",
    )
    monkeypatch.setattr(
        difficulty_card_workflow.upload_service_minio,
        "save_generated_image",
        lambda user_id, data, *, file_name="knowledge-card": _fake_save(
            user_id, data, file_name=file_name, resource_type=1, suffix=".png"
        ),
    )
    monkeypatch.setattr(
        difficulty_card_workflow.upload_service_minio,
        "save_generated_audio",
        lambda user_id, data, *, file_name="knowledge-card-podcast": _fake_save(
            user_id, data, file_name=file_name, resource_type=2, suffix=".mp3"
        ),
    )
    monkeypatch.setattr(
        difficulty_card_workflow.minio_client,
        "presigned_url_for_storage_path",
        lambda _path: "http://minio.local/card-asset",
    )
    return calls


def _new_session(user_id: int) -> dict:
    return session_repo.insert(
        {"user_id": user_id, "title": "学习会话", "session_mode": 0}
    )


def _sse_event(resp: httpx.Response, name: str) -> dict | None:
    """从 SSE 响应体取指定事件的 JSON 载荷。"""
    for block in resp.text.split("\n\n"):
        event = data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line[len("event: ") :]
            elif line.startswith("data: "):
                data = line[len("data: ") :]
        if event == name and data is not None:
            return json.loads(data)
    return None


def test_difficulty_capability_registered() -> None:
    """难点学习已登记为 task 能力；必须命中关键词 / 语义 / 显式指令才触发。"""
    capability = get_capability(DIFFICULTY_AGENT)

    assert capability is not None and capability.kind == "task"
    assert "知识卡" in capability.triggers


def test_image_prompt_is_deterministic() -> None:
    """绘图提示词由卡片字段确定性拼接，并包含竖版信息图约束。"""
    prompt = difficulty_learner.build_image_prompt(CARD)

    assert CARD["title"] in prompt
    assert CARD["summary"] in prompt
    assert CARD["points"][0]["tip"] in prompt
    assert "竖版" in prompt
    assert prompt == difficulty_learner.build_image_prompt(CARD)


def test_podcast_topic_is_deterministic() -> None:
    """播客话题与绘图同源：复用同一份卡片原料，且不调用模型。"""
    topic = difficulty_learner.build_podcast_topic(CARD)

    assert CARD["title"] in topic
    assert CARD["summary"] in topic
    assert CARD["points"][0]["tip"] in topic
    assert "双人" in topic
    assert topic == difficulty_learner.build_podcast_topic(CARD)


def _server_frame(event: int, payload: bytes, session_id: str = "sid-1") -> bytes:
    encoded_session = session_id.encode("utf-8")
    return (
        bytes([0x11, 0x94, 0x10, 0x00])
        + struct.pack(">i", event)
        + struct.pack(">I", len(encoded_session))
        + encoded_session
        + struct.pack(">I", len(payload))
        + payload
    )


def test_podcast_frame_encoding() -> None:
    """上行帧固定：v1 / 4 字节头 / message type 1 / JSON / 带 event。"""
    frame = podcast_service._encode_frame(
        podcast_service.EVENT_START_SESSION, b'{"action":0}', "sid-1"
    )

    assert frame[:4] == bytes([0x11, 0x14, 0x10, 0x00])
    assert struct.unpack_from(">i", frame, 4)[0] == 100
    assert struct.unpack_from(">I", frame, 8)[0] == 5
    assert frame[12:17] == b"sid-1"
    assert struct.unpack_from(">I", frame, 17)[0] == len(b'{"action":0}')
    assert frame[21:] == b'{"action":0}'


def test_podcast_frame_parsing() -> None:
    """下行音频帧取出 payload；错误帧带 error code 与原始报文。"""
    audio = podcast_service._parse_frame(
        _server_frame(podcast_service.EVENT_ROUND_RESPONSE, b"ID3audio")
    )
    assert audio.event == podcast_service.EVENT_ROUND_RESPONSE
    assert audio.payload == b"ID3audio"
    assert audio.error_code is None

    error = podcast_service._parse_frame(
        bytes([0x11, 0xF0, 0x10, 0x00])
        + struct.pack(">i", 45000000)
        + b'{"error":"quota"}'
    )
    assert error.event is None
    assert error.error_code == 45000000
    assert error.payload == b'{"error":"quota"}'


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
            "preferred_agent": DIFFICULTY_AGENT,
            "session_id": session["id"],
            "request_text": "讲讲 Python GIL",
        },
    )

    assert resp.status_code == 200, resp.text
    task = _sse_event(resp, "task")
    assert task is not None and task["kind"] == "knowledge_card"
    data = task["payload"]
    assert data["status"] == "completed"
    assert data["title"] == CARD["title"]
    assert data["image_url"] == "http://minio.local/card-asset"
    assert data["audio_resource_id"] is not None
    assert data["audio_url"] == "http://minio.local/card-asset"
    assert calls

    run = workflow_run_repo.get_for_user(data["run_id"], auth_user["id"])
    assert run["status"] == "completed"
    assert run["state_json"]["resource_id"] == data["resource_id"]
    assert run["state_json"]["audio_resource_id"] == data["audio_resource_id"]
    assert run["state_json"]["podcast_topic"]

    messages = message_repo.list_by_session(session["id"], 0, 20)
    card_messages = [row for row in messages if row.get("response_segments")]
    assert len(card_messages) == 1
    assert card_messages[0]["request_id"] == f"{data['run_id']}:card"
    assert card_messages[0]["response_payload"] == {"type": "knowledge_card"}
    segments = card_messages[0]["response_segments"]
    assert [segment["type"] for segment in segments] == ["image", "audio"]
    assert segments[0]["resource_id"] == data["resource_id"]
    assert segments[1]["resource_id"] == data["audio_resource_id"]


async def test_podcast_failure_keeps_card_message(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    monkeypatch,
) -> None:
    """音频是加分项：生成失败仍返回知识卡，消息只挂 image 段。"""
    _patch_pipeline(monkeypatch)
    monkeypatch.setattr(
        difficulty_card_workflow.podcast_service,
        "generate_podcast",
        lambda _topic: (_ for _ in ()).throw(RuntimeError("PODCAST_TTS 未配置")),
    )
    session = _new_session(auth_user["id"])

    resp = await client.post(
        BASE,
        headers=auth_headers,
        json={
            "preferred_agent": DIFFICULTY_AGENT,
            "session_id": session["id"],
            "request_text": "讲讲 Python GIL",
        },
    )

    assert resp.status_code == 200, resp.text
    data = _sse_event(resp, "task")["payload"]
    assert data["status"] == "completed"
    assert data["audio_resource_id"] is None
    assert data["audio_url"] is None

    messages = message_repo.list_by_session(session["id"], 0, 20)
    card_messages = [row for row in messages if row.get("response_segments")]
    assert len(card_messages) == 1
    segments = card_messages[0]["response_segments"]
    assert [segment["type"] for segment in segments] == ["image"]


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
            "preferred_agent": DIFFICULTY_AGENT,
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
    segments = listed.json()["data"]["items"][0]["response_segments"]
    assert [segment["type"] for segment in segments] == ["image", "audio"]
    assert all(segment["url"] == "http://minio.local/card-asset" for segment in segments)


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
            "preferred_agent": DIFFICULTY_AGENT,
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
            "preferred_agent": DIFFICULTY_AGENT,
            "session_id": session["id"],
            "request_text": "讲讲 Python GIL",
        },
    )

    assert resp.status_code == 200, resp.text
    error = _sse_event(resp, "error")
    assert error is not None and error["code"] == 503
    assert _sse_event(resp, "task") is None
    with SessionLocal() as db:
        runs = db.scalars(
            select(WorkflowRun).where(WorkflowRun.session_id == session["id"])
        ).all()
    assert len(runs) == 1
    assert runs[0].status == "failed"
    assert "SEEDREAM_API_KEY" in runs[0].error_message
