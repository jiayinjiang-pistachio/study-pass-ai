"""面试复盘与面试笔记：服务幂等、失败落库、结束面试自动触发、笔记归档。"""

import json

import httpx
import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app.core import config
from app.core.exceptions import BusinessException
from app.db import interview_repo, message_repo, session_repo
from app.services import interview_evaluation_service, note_archive_service
from app.services.interview_evaluation_service import InterviewEvaluationService
from app.services.note_archive_service import NoteArchiveService
from app.services.note_service import NoteService

EVAL_JSON = json.dumps(
    {
        "score": 82,
        "strengths": ["表达清晰", "项目细节完整"],
        "weaknesses": ["索引原理不深"],
        "review": "继续练习索引与事务隔离级别。",
    },
    ensure_ascii=False,
)

NOTE_MARKDOWN = """# 模拟面试复盘

## 面试概览
本次面试共 3 轮问答。

## 亮点表现
- 表达清晰

## 问题复盘
- 索引原理回答不完整

## 改进建议
- 复习 B+ 树与事务隔离级别"""


def _new_session(user_id: int, session_mode: int = 1) -> dict:
    return session_repo.insert(
        {"user_id": user_id, "title": "面试会话", "session_mode": session_mode}
    )


def _new_interview(user_id: int, session_id: int, status: int = 1) -> dict:
    """直接落库造面试记录；入口消息与面试通过 message_id 关联。"""
    message = message_repo.insert(
        {
            "user_id": user_id,
            "session_id": session_id,
            "select_mode": 4,
            "request_id": f"interview-{user_id}-{session_id}",
            "request_text": "开始面试",
            "response_text": "",
            "status": 1,
        }
    )
    return interview_repo.insert(
        {
            "user_id": user_id,
            "session_id": session_id,
            "message_id": message["id"],
            "qa_object": [
                {
                    "id": 1,
                    "question": "讲讲 MySQL 索引。",
                    "answer": "B+ 树。",
                    "created_at": 1,
                }
            ],
            "interview_duration": 300,
            "status": status,
        }
    )


@pytest.fixture
def fake_eval_model(monkeypatch) -> None:
    """把复盘模型替换为固定 JSON，避免真实模型调用。"""
    monkeypatch.setattr(
        interview_evaluation_service,
        "get_chat_model",
        lambda: RunnableLambda(lambda _: AIMessage(content=EVAL_JSON)),
    )


def test_evaluate_session_writes_message_and_is_idempotent(
    auth_user: dict, fake_eval_model: None
) -> None:
    """最近一次已结束面试 → 生成复盘消息，重复调用复用同一条消息。"""
    session = _new_session(auth_user["id"])
    interview = _new_interview(auth_user["id"], session["id"])
    service = InterviewEvaluationService()

    first = service.evaluate_session(auth_user["id"], session["id"])
    assert first["status"] == "completed"
    assert first["score"] == 82
    assert first["run_id"] == f"interview:{interview['id']}"

    message = message_repo.get(first["message_id"])
    assert message is not None
    assert message["status"] == interview_evaluation_service.MSG_STATUS_DONE
    assert message["response_payload"]["type"] == "interview_evaluation"
    assert message["response_payload"]["score"] == 82
    assert "82/100" in message["response_text"]

    # 第二次调用不应再次生成，直接返回已落库结果
    second = service.evaluate_session(auth_user["id"], session["id"])
    assert second["message_id"] == first["message_id"]
    assert second["score"] == 82


def test_evaluate_session_rejects_without_completed_interview(
    auth_user: dict, fake_eval_model: None
) -> None:
    """没有已结束面试 → 409，不创建占位消息。"""
    session = _new_session(auth_user["id"])
    _new_interview(auth_user["id"], session["id"], status=0)

    with pytest.raises(BusinessException) as exc:
        InterviewEvaluationService().evaluate_session(
            auth_user["id"], session["id"]
        )
    assert exc.value.http_status == 409


def test_evaluate_session_isolated_by_user(
    auth_user: dict, other_auth: tuple[dict, dict], fake_eval_model: None
) -> None:
    """别人的已结束面试不能被当前用户复盘。"""
    other_user, _ = other_auth
    session = _new_session(other_user["id"])
    _new_interview(other_user["id"], session["id"])

    with pytest.raises(BusinessException) as exc:
        InterviewEvaluationService().evaluate_session(
            auth_user["id"], session["id"]
        )
    assert exc.value.http_status == 409


def test_evaluate_session_marks_message_failed_on_model_error(
    auth_user: dict, monkeypatch
) -> None:
    """模型失败 → 异常上抛，占位消息置失败，不影响面试记录本身。"""
    session = _new_session(auth_user["id"])
    _new_interview(auth_user["id"], session["id"])

    def _boom(*args, **kwargs):
        raise RuntimeError("model boom")

    monkeypatch.setattr(
        interview_evaluation_service, "_generate_evaluation", _boom
    )

    with pytest.raises(RuntimeError):
        InterviewEvaluationService().evaluate_session(
            auth_user["id"], session["id"]
        )

    rows = message_repo.list_all_by_session(session["id"])
    failed = [row for row in rows if row["status"] == 2]
    assert failed
    assert failed[-1]["response_text"] == "面试复盘生成失败，请稍后重试。"
    # 原面试记录仍是已完成状态
    assert interview_repo.get_latest_completed_for_session(
        auth_user["id"], session["id"]
    ) is not None


async def test_finish_interview_triggers_auto_evaluation(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    monkeypatch,
) -> None:
    """开启自动复盘时，结束面试会在后台登记复盘任务。"""
    from app.services import voice_interview_service

    session = _new_session(auth_user["id"])
    interview = _new_interview(auth_user["id"], session["id"], status=0)
    monkeypatch.setattr(config, "INTERVIEW_EVAL_AUTO", True)
    monkeypatch.setattr(
        voice_interview_service.VoiceInterviewService,
        "stop_voice_chat",
        lambda self, interview_id: True,
    )
    calls: list[tuple[int, int]] = []
    monkeypatch.setattr(
        interview_evaluation_service,
        "evaluate_session_background",
        lambda user_id, session_id: calls.append((user_id, session_id)),
    )

    resp = await client.post(
        f"/api/interviews/{interview['id']}/voice/finish",
        headers=auth_headers,
        json={"qa_object": [], "interview_duration": 60},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["session_id"] == session["id"]
    assert calls == [(auth_user["id"], session["id"])]


async def test_finish_interview_skips_auto_evaluation_when_disabled(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    monkeypatch,
) -> None:
    """关闭自动复盘时（测试默认），结束面试不登记后台任务。"""
    from app.services import voice_interview_service

    session = _new_session(auth_user["id"])
    interview = _new_interview(auth_user["id"], session["id"], status=0)
    monkeypatch.setattr(
        voice_interview_service.VoiceInterviewService,
        "stop_voice_chat",
        lambda self, interview_id: True,
    )
    calls: list[tuple[int, int]] = []
    monkeypatch.setattr(
        interview_evaluation_service,
        "evaluate_session_background",
        lambda user_id, session_id: calls.append((user_id, session_id)),
    )

    resp = await client.post(
        f"/api/interviews/{interview['id']}/voice/finish",
        headers=auth_headers,
        json={"qa_object": [], "interview_duration": 60},
    )
    assert resp.status_code == 200, resp.text
    assert calls == []


def test_interview_note_archive_and_idempotent_save(
    auth_user: dict, monkeypatch
) -> None:
    """面试归档：生成 Markdown 笔记并按 (user, interview) 幂等保存。"""
    session = _new_session(auth_user["id"])
    interview = _new_interview(auth_user["id"], session["id"])
    monkeypatch.setattr(
        note_archive_service,
        "_generate_markdown",
        lambda *args, **kwargs: NOTE_MARKDOWN,
    )

    archive = NoteArchiveService().archive_from_interview(
        auth_user["id"], interview["id"]
    )
    assert archive["title"] == "模拟面试复盘"
    assert archive["tags"] == [note_archive_service.NOTE_TAG_INTERVIEW]
    assert archive["metadata"]["interview_id"] == interview["id"]
    assert archive["metadata"]["qa_count"] == 1

    first = NoteService().save_interview_note(
        auth_user["id"], session["id"], interview["id"], archive
    )
    second = NoteService().save_interview_note(
        auth_user["id"], session["id"], interview["id"], archive
    )
    assert first["note_id"] == second["note_id"]
    assert first["note_status"] == "saved"
    assert second["note_status"] == "existing"


def test_interview_note_requires_finished_interview(auth_user: dict) -> None:
    """未结束的面试不能生成笔记。"""
    session = _new_session(auth_user["id"])
    interview = _new_interview(auth_user["id"], session["id"], status=0)

    with pytest.raises(BusinessException) as exc:
        NoteArchiveService().archive_from_interview(
            auth_user["id"], interview["id"]
        )
    assert exc.value.http_status == 409
