"""note_archiver 笔记归档：state / run_id 两种入口与 A2A handler 集成。"""

import uuid

import pytest

from app.core.exceptions import BusinessException
from app.db import session_repo, workflow_run_repo
from app.services.a2a_handoff_service import A2AHandoffService
from app.services.note_archive_service import NoteArchiveService


def _state(**overrides) -> dict:
    state = {
        "run_id": "run-note-1",
        "user_id": 1,
        "session_id": 9,
        "request_text": "测一下 Python 基础",
        "quiz": [
            {
                "question_id": 1,
                "type": "radio",
                "stem": "HTTP 404 表示什么？",
                "options": [{"key": "A", "text": "未找到"}, {"key": "B", "text": "成功"}],
            },
            {
                "question_id": 2,
                "type": "textarea",
                "stem": "简述索引的作用。",
                "options": [],
            },
        ],
        "answers": [
            {"question_id": 1, "value": "A"},
            {"question_id": 2, "value": "加速查询"},
        ],
        "evaluation": [
            {"question_id": 1, "correct": True, "comment": "正确"},
            {"question_id": 2, "correct": False, "comment": "要点不完整"},
        ],
        "score": 50,
        "weaknesses": ["索引原理"],
        "review": "建议补充 B+ 树知识。",
        "a2a_envelope": {
            "from_agent": "learning_evaluator",
            "next_agent": "note_archiver",
        },
    }
    state.update(overrides)
    return state


def test_archive_from_state_builds_renderable_note() -> None:
    """state 直接生成笔记：四个 Markdown 章节、标签、元数据齐全。"""
    note = NoteArchiveService().archive_from_state(1, _state())

    assert note["title"] == "学习测评笔记：测一下 Python 基础"
    assert note["weaknesses"] == ["索引原理"]
    assert note["tags"] == ["学习测评", "索引原理"]
    assert note["a2a_envelope"]["next_agent"] == "note_archiver"
    for section in ("测评概览", "薄弱点总结", "错题复盘", "复习建议"):
        assert f"## {section}" in note["content"]
    assert "第 2 题：简述索引的作用。" in note["content"]
    assert "- 你的作答：加速查询" in note["content"]
    assert "- 点评：要点不完整" in note["content"]
    assert note["metadata"] == {
        "run_id": "run-note-1",
        "user_id": 1,
        "session_id": 9,
        "workflow_type": "learning_quiz",
        "score": 50,
        "question_count": 2,
        "correct_count": 1,
        "wrong_count": 1,
        "weakness_count": 1,
        "generated_at": note["metadata"]["generated_at"],
    }


def test_archive_from_state_without_weakness() -> None:
    """无薄弱点 / 无错题：正文给出正向结论，不产生额外标签。"""
    note = NoteArchiveService().archive_from_state(
        1,
        _state(
            weaknesses=[],
            evaluation=[
                {"question_id": 1, "correct": True, "comment": "正确"},
                {"question_id": 2, "correct": True, "comment": "完整"},
            ],
            score=100,
        ),
    )

    assert note["tags"] == ["学习测评"]
    assert "本次测评未发现明显薄弱点。" in note["content"]
    assert "本次测评没有错题，继续保持。" in note["content"]
    assert note["metadata"]["correct_count"] == 2
    assert note["metadata"]["wrong_count"] == 0


def test_archive_from_state_rejects_empty_state() -> None:
    """空 state 不能生成笔记，交业务层统一 400。"""
    with pytest.raises(BusinessException) as exc_info:
        NoteArchiveService().archive_from_state(1, {})

    assert exc_info.value.http_status == 400


def test_archive_from_run_reads_persisted_state(auth_user: dict) -> None:
    """按 run_id 回源 workflow_runs.state_json，并保持用户隔离。"""
    session = session_repo.insert(
        {"user_id": auth_user["id"], "title": "笔记会话", "session_mode": 0}
    )
    run_id = str(uuid.uuid4())
    workflow_run_repo.insert(
        {
            "run_id": run_id,
            "user_id": auth_user["id"],
            "session_id": session["id"],
            "workflow_type": "learning_quiz",
            "status": "completed",
            "state_json": _state(
                run_id=run_id, user_id=auth_user["id"], session_id=session["id"]
            ),
        }
    )

    note = NoteArchiveService().archive_from_run(auth_user["id"], run_id)

    assert note["metadata"]["run_id"] == run_id
    assert note["metadata"]["user_id"] == auth_user["id"]

    with pytest.raises(BusinessException) as exc_info:
        NoteArchiveService().archive_from_run(auth_user["id"] + 1, run_id)
    assert exc_info.value.http_status == 404


def test_dispatch_runs_note_archiver_from_context_state() -> None:
    """默认注册的 handler 优先使用派发上下文中的完整 state。"""
    result = A2AHandoffService().dispatch(
        {
            "from_agent": "learning_evaluator",
            "payload_type": "weak_points",
            "payload": {"score": 50, "weaknesses": ["索引原理"]},
            "next_agent": "note_archiver",
            "confidence": 0.9,
        },
        context={"user_id": 1, "run_id": "run-note-1", "state": _state()},
    )

    assert result["status"] == "completed"
    assert result["next_agent"] == "note_archiver"
    assert result["result"]["title"] == "学习测评笔记：测一下 Python 基础"
