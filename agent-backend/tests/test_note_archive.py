"""note_archiver 笔记归档：Markdown 生成、占位符校验、落库与 A2A 集成。"""

import uuid

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app.core.exceptions import BusinessException, SystemException
from app.db import note_repo, session_repo, workflow_run_repo
from app.services import note_archive_service, prompt_template_service
from app.services.a2a_handoff_service import A2AHandoffService
from app.services.note_archive_service import NoteArchiveService
from app.services.note_service import NOTE_STATUS_EXISTING, NOTE_STATUS_SAVED, NoteService

NOTE_MARKDOWN = """# 学习测评笔记：Python 基础
## 测评概览
得分 50 分，共 2 题。
## 薄弱点总结
- 索引原理
## 错题复盘
### 第 2 题：简述索引的作用。
- 你的作答：加速查询
- 点评：要点不完整
## 复习建议
建议补充 B+ 树知识。"""


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
    }
    state.update(overrides)
    return state


def _patch_model(monkeypatch, *responses: str) -> None:
    """按调用顺序返回 Markdown；记录每次调用收到的消息列表。"""
    queue = list(responses)
    captured: list[list] = []

    def _invoke(prompt_value: object) -> AIMessage:
        messages = (
            prompt_value.to_messages()
            if hasattr(prompt_value, "to_messages")
            else list(prompt_value)  # type: ignore[arg-type]
        )
        captured.append(messages)
        if not queue:
            raise AssertionError("模型调用次数超出预期")
        return AIMessage(content=queue.pop(0))

    monkeypatch.setattr(
        note_archive_service, "get_chat_model", lambda: RunnableLambda(_invoke)
    )
    return captured


def test_archive_from_state_builds_markdown_note(monkeypatch) -> None:
    """state 生成笔记：标题来自 Markdown，tags / metadata 由服务补齐。"""
    _patch_model(monkeypatch, NOTE_MARKDOWN)

    note = NoteArchiveService().archive_from_state(1, _state())

    assert set(note) == {"title", "content", "tags", "metadata"}
    assert note["title"] == "学习测评笔记：Python 基础"
    assert note["content"] == NOTE_MARKDOWN
    assert note["tags"] == ["学习测评", "索引原理"]
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


def test_archive_from_state_injects_template_variables(monkeypatch) -> None:
    """调用模型前把 {weak_topics} / {question_count} 等替换成实际值。"""
    monkeypatch.setattr(
        prompt_template_service,
        "get_combined_template",
        lambda *args, **kwargs: {
            "final_template": (
                "薄弱点：{weak_topics}；题数：{question_count}；"
                "得分：{score}；答对：{correct_count}；答错：{wrong_count}"
            ),
            "variables": [],
        },
    )
    messages = _patch_model(monkeypatch, NOTE_MARKDOWN)

    NoteArchiveService().archive_from_state(1, _state())

    system_prompt = messages[0][0].content
    assert "薄弱点：索引原理" in system_prompt
    assert "题数：2" in system_prompt
    assert "得分：50" in system_prompt
    assert "答对：1" in system_prompt
    assert "答错：1" in system_prompt
    assert "{weak_topics}" not in system_prompt


def test_archive_from_state_falls_back_title(monkeypatch) -> None:
    """没有可用标题时用测评需求拼一个稳定标题。"""
    _patch_model(monkeypatch, "## 测评概览\n\n本次表现一般。")

    note = NoteArchiveService().archive_from_state(1, _state())

    assert note["title"] == "学习测评笔记：测一下 Python 基础"


def test_archive_from_state_rejects_leftover_placeholder(monkeypatch) -> None:
    """正文残留未替换占位符时拒绝归档。"""
    _patch_model(monkeypatch, "# 标题\n\n薄弱点：{weak_topics}")

    with pytest.raises(SystemException) as exc_info:
        NoteArchiveService().archive_from_state(1, _state())

    assert "未替换" in exc_info.value.message


def test_archive_from_state_rejects_empty_state() -> None:
    """空 state 不能生成笔记。"""
    with pytest.raises(BusinessException) as exc_info:
        NoteArchiveService().archive_from_state(1, {})

    assert exc_info.value.http_status == 400


def test_note_service_saves_idempotently(auth_user: dict) -> None:
    """同一 user_id + run 只落一条笔记；重复保存返回 existing。"""
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
            "state_json": _state(run_id=run_id, user_id=auth_user["id"]),
        }
    )
    archive = {
        "title": "笔记标题",
        "content": "# 笔记标题\n正文",
        "tags": ["学习测评"],
        "metadata": {"run_id": run_id},
    }

    first = NoteService().save_learning_quiz_note(
        auth_user["id"], session["id"], run_id, archive
    )
    second = NoteService().save_learning_quiz_note(
        auth_user["id"], session["id"], run_id, {**archive, "title": "新标题"}
    )

    assert first["note_status"] == NOTE_STATUS_SAVED
    assert second["note_id"] == first["note_id"]
    assert second["note_status"] == NOTE_STATUS_EXISTING

    row = note_repo.get_by_user_and_run(auth_user["id"], run_id)
    assert row["title"] == "笔记标题"
    assert row["metadata_json"] == {"run_id": run_id}

    run = workflow_run_repo.get_for_user(run_id, auth_user["id"])
    assert run["state_json"]["note_id"] == first["note_id"]
    assert run["state_json"]["note_status"] == NOTE_STATUS_SAVED


def test_archive_from_run_reads_persisted_state(
    auth_user: dict, monkeypatch
) -> None:
    """按 run_id 回源 workflow_runs.state_json，并保持用户隔离。"""
    _patch_model(monkeypatch, NOTE_MARKDOWN)
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


def test_dispatch_runs_note_archiver_generate_then_save(
    auth_user: dict, monkeypatch
) -> None:
    """默认注册的 handler：先生成 Markdown，再保存并回写运行状态。"""
    _patch_model(monkeypatch, NOTE_MARKDOWN)
    session = session_repo.insert(
        {"user_id": auth_user["id"], "title": "笔记会话", "session_mode": 0}
    )
    run_id = str(uuid.uuid4())
    state = _state(
        run_id=run_id, user_id=auth_user["id"], session_id=session["id"]
    )
    workflow_run_repo.insert(
        {
            "run_id": run_id,
            "user_id": auth_user["id"],
            "session_id": session["id"],
            "workflow_type": "learning_quiz",
            "status": "completed",
            "state_json": state,
        }
    )

    result = A2AHandoffService().dispatch(
        {
            "from_agent": "learning_evaluator",
            "payload_type": "weak_points",
            "payload": {"score": 50, "weaknesses": ["索引原理"]},
            "next_agent": "note_archiver",
            "confidence": 0.9,
        },
        context={
            "user_id": auth_user["id"],
            "run_id": run_id,
            "session_id": session["id"],
            "state": state,
        },
    )

    assert result["status"] == "completed"
    assert result["next_agent"] == "note_archiver"
    assert result["result"]["note_status"] == NOTE_STATUS_SAVED
    note = note_repo.get_by_user_and_run(auth_user["id"], run_id)
    assert note["id"] == result["result"]["note_id"]
    assert note["title"] == "学习测评笔记：Python 基础"
    run = workflow_run_repo.get_for_user(run_id, auth_user["id"])
    assert run["state_json"]["note_id"] == note["id"]
