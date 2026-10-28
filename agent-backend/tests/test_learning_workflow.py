"""学习测评工作流测试。

模型调用替换为假的 Runnable，不依赖真实大模型与 API Key；
覆盖：出题归一化、状态落库、评分闭环、作答校验、越权隔离与失败落库。
"""

import json

import httpx
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from sqlalchemy import select

from app.db import session_repo, workflow_run_repo
from app.db.models import WorkflowRun
from app.db.session import SessionLocal
from app.services import learning_workflow

QUIZ_JSON = """```json
{
  "questions": [
    {
      "type": "single_choice",
      "stem": "HTTP 状态码 404 表示什么？",
      "options": [{"key": "A", "text": "未找到"}, {"key": "B", "text": "成功"}]
    },
    {
      "type": "multiple_choice",
      "stem": "下列属于关系型数据库的有？",
      "options": [{"key": "A", "text": "MySQL"}, {"key": "B", "text": "Redis"}]
    },
    {
      "type": "short_answer",
      "stem": "简述索引的作用。",
      "options": []
    },
    {
      "type": "unknown",
      "stem": "这道题会被题目数量截断",
      "options": []
    }
  ]
}
```"""

EVAL_JSON = json.dumps(
    {
        "score": 67,
        "evaluation": [
            {"question_id": 1, "correct": True, "comment": "正确"},
            {"question_id": 2, "correct": False, "comment": "Redis 是 KV 存储"},
            {"question_id": 3, "correct": True, "comment": "要点基本覆盖"},
            {"question_id": 99, "correct": True, "comment": "非法题目应被忽略"},
        ],
        "weaknesses": ["数据库选型", "索引原理"],
        "review": "建议补充索引与存储选型知识。",
    },
    ensure_ascii=False,
)


def _patch_model(monkeypatch, *responses: str) -> None:
    """按调用顺序返回预设文本；调用次数超出预期视为用例失败。"""
    queue = list(responses)

    def _invoke(_: object) -> AIMessage:
        if not queue:
            raise AssertionError("模型调用次数超出预期")
        return AIMessage(content=queue.pop(0))

    monkeypatch.setattr(
        learning_workflow, "get_chat_model", lambda: RunnableLambda(_invoke)
    )


def _new_session(user_id: int) -> dict:
    return session_repo.insert(
        {"user_id": user_id, "title": "测评会话", "session_mode": 0}
    )


async def _start(client: httpx.AsyncClient, headers: dict, session_id: int) -> dict:
    resp = await client.post(
        "/api/learning-workflows/start",
        headers=headers,
        json={
            "session_id": session_id,
            "request_text": "测一下 Python 基础",
            "question_count": 3,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


async def test_start_generates_quiz_and_persists(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    monkeypatch,
) -> None:
    """出题成功：返回结构化题目，状态落 workflow_runs。"""
    session = _new_session(auth_user["id"])
    _patch_model(monkeypatch, QUIZ_JSON)

    data = await _start(client, auth_headers, session["id"])

    assert data["status"] == learning_workflow.STATUS_QUIZ_READY
    assert data["run_id"]
    assert [q["question_id"] for q in data["quiz"]] == [1, 2, 3]
    # 题型归一化：未知类型降级为简答；题目数量按请求截断
    assert [q["type"] for q in data["quiz"]] == [
        "single_choice",
        "multiple_choice",
        "short_answer",
    ]
    # 不向前端泄漏标准答案
    assert all("answer" not in q for q in data["quiz"])

    row = workflow_run_repo.get_for_user(data["run_id"], auth_user["id"])
    assert row is not None
    assert row["status"] == learning_workflow.STATUS_QUIZ_READY
    assert row["workflow_type"] == learning_workflow.WORKFLOW_TYPE_LEARNING_QUIZ
    assert row["state_json"]["quiz"] == data["quiz"]
    assert row["state_json"]["provider"] == learning_workflow.LLM_PROVIDER


async def test_start_rejects_foreign_session(
    client: httpx.AsyncClient,
    other_auth: tuple[dict, dict],
    auth_headers: dict,
    monkeypatch,
) -> None:
    """他人会话 → 404，且不会调用模型、不会产生运行记录。"""
    other_user, _ = other_auth
    session = _new_session(other_user["id"])
    _patch_model(monkeypatch)  # 无预设响应：一旦调用即失败

    resp = await client.post(
        "/api/learning-workflows/start",
        headers=auth_headers,
        json={"session_id": session["id"], "request_text": "越权测试"},
    )

    assert resp.status_code == 404
    assert resp.json()["code"] == 404


async def test_start_marks_failed_on_invalid_model_output(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    monkeypatch,
) -> None:
    """模型输出非 JSON → 502，运行记录置为 failed 并保留错误原因。"""
    session = _new_session(auth_user["id"])
    _patch_model(monkeypatch, "抱歉，我无法出题")

    resp = await client.post(
        "/api/learning-workflows/start",
        headers=auth_headers,
        json={"session_id": session["id"], "request_text": "出题"},
    )

    assert resp.status_code == 502
    assert resp.json()["code"] == 502

    with SessionLocal() as db:
        row = db.scalars(
            select(WorkflowRun).where(WorkflowRun.user_id == auth_user["id"])
        ).one()
    assert row.status == learning_workflow.STATUS_FAILED
    assert "JSON" in (row.error_message or "")


async def test_submit_scores_and_completes(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    monkeypatch,
) -> None:
    """提交作答：评分、逐题点评、薄弱点落库，重复提交返回 409。"""
    session = _new_session(auth_user["id"])
    _patch_model(monkeypatch, QUIZ_JSON, EVAL_JSON)
    started = await _start(client, auth_headers, session["id"])

    answers = [
        {"question_id": 1, "value": "A"},
        {"question_id": 2, "value": ["A"]},
        {"question_id": 3, "value": "加速查询"},
    ]
    resp = await client.post(
        f"/api/learning-workflows/{started['run_id']}/submit",
        headers=auth_headers,
        json={"answers": answers},
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["status"] == learning_workflow.STATUS_COMPLETED
    assert data["score"] == 67
    assert [item["question_id"] for item in data["evaluation"]] == [1, 2, 3]
    assert data["weaknesses"] == ["数据库选型", "索引原理"]
    assert data["review"] == "建议补充索引与存储选型知识。"

    row = workflow_run_repo.get_for_user(started["run_id"], auth_user["id"])
    assert row["status"] == learning_workflow.STATUS_COMPLETED
    assert isinstance(row["completed_at"], int)
    assert row["state_json"]["answers"] == answers
    assert row["state_json"]["score"] == 67

    # 重复提交被拒绝，且不覆盖已完成结果
    again = await client.post(
        f"/api/learning-workflows/{started['run_id']}/submit",
        headers=auth_headers,
        json={"answers": answers},
    )
    assert again.status_code == 409
    assert "已提交" in again.json()["message"]


async def test_submit_rejects_incomplete_answers(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    monkeypatch,
) -> None:
    """缺题 → 422，不调用模型。"""
    session = _new_session(auth_user["id"])
    _patch_model(monkeypatch, QUIZ_JSON)  # 评测阶段不应有模型调用
    started = await _start(client, auth_headers, session["id"])

    resp = await client.post(
        f"/api/learning-workflows/{started['run_id']}/submit",
        headers=auth_headers,
        json={
            "answers": [
                {"question_id": 1, "value": "A"},
                {"question_id": 2, "value": ["A"]},
            ]
        },
    )

    assert resp.status_code == 422
    assert "未作答" in resp.json()["message"]


async def test_submit_rejects_invalid_option(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    monkeypatch,
) -> None:
    """选中不存在的选项 → 422。"""
    session = _new_session(auth_user["id"])
    _patch_model(monkeypatch, QUIZ_JSON)
    started = await _start(client, auth_headers, session["id"])

    resp = await client.post(
        f"/api/learning-workflows/{started['run_id']}/submit",
        headers=auth_headers,
        json={
            "answers": [
                {"question_id": 1, "value": "Z"},
                {"question_id": 2, "value": ["A"]},
                {"question_id": 3, "value": "索引"},
            ]
        },
    )

    assert resp.status_code == 422
    assert "选项非法" in resp.json()["message"]


async def test_submit_rejects_foreign_run(
    client: httpx.AsyncClient,
    other_auth: tuple[dict, dict],
    auth_headers: dict,
) -> None:
    """他人的 run_id → 404。"""
    other_user, _ = other_auth
    other_session = _new_session(other_user["id"])

    # 直接用仓储造一条他人的运行记录，避免为越权用例再伪造一次登录
    run_id = "00000000-0000-0000-0000-000000000001"
    workflow_run_repo.insert(
        {
            "run_id": run_id,
            "user_id": other_user["id"],
            "session_id": other_session["id"],
            "workflow_type": learning_workflow.WORKFLOW_TYPE_LEARNING_QUIZ,
            "status": learning_workflow.STATUS_QUIZ_READY,
            "state_json": {"quiz": [], "status": learning_workflow.STATUS_QUIZ_READY},
        }
    )

    submit = await client.post(
        f"/api/learning-workflows/{run_id}/submit",
        headers=auth_headers,
        json={"answers": [{"question_id": 1, "value": "A"}]},
    )
    assert submit.status_code == 404

    detail = await client.get(
        f"/api/learning-workflows/{run_id}", headers=auth_headers
    )
    assert detail.status_code == 404


async def test_get_returns_full_state(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    monkeypatch,
) -> None:
    """详情接口返回状态与完整 state。"""
    session = _new_session(auth_user["id"])
    _patch_model(monkeypatch, QUIZ_JSON)
    started = await _start(client, auth_headers, session["id"])

    resp = await client.get(
        f"/api/learning-workflows/{started['run_id']}", headers=auth_headers
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["run_id"] == started["run_id"]
    assert data["status"] == learning_workflow.STATUS_QUIZ_READY
    assert data["state"]["request_text"] == "测一下 Python 基础"
    assert data["state"]["quiz"] == started["quiz"]
