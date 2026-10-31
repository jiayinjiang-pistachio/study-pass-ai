"""学习测评工作流测试。

模型调用替换为假的 Runnable，不依赖真实大模型与 API Key；
覆盖：出题归一化、interrupt 暂停点、状态落库、评分闭环、作答校验、
checkpoint 失效、越权隔离与失败落库。
"""

import json

import httpx
import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from sqlalchemy import select

from app.agent.a2a import A2AEnvelope, decide_next_agent
from app.agent.workflows import learning_quiz
from app.agent.workflows.checkpoint import (
    build_thread_config,
    get_workflow_checkpointer,
)
from app.db import message_repo, session_repo, workflow_run_repo
from app.db.models import WorkflowRun
from app.db.session import SessionLocal
from app.services import learning_workflow

QUIZ_JSON = """```json
{
  "questions": [
    {
      "type": "radio",
      "stem": "HTTP 状态码 404 表示什么？",
      "options": [{"key": "A", "text": "未找到"}, {"key": "B", "text": "成功"}]
    },
    {
      "type": "checkbox",
      "stem": "下列属于关系型数据库的有？",
      "options": [{"key": "A", "text": "MySQL"}, {"key": "B", "text": "Redis"}]
    },
    {
      "type": "textarea",
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

EVAL_DISPLAY_TEXT = "本次得分 67 分，重点巩固数据库选型与索引原理，建议按点评逐条复盘。"

EVAL_JSON = json.dumps(
    {
        "display_text": EVAL_DISPLAY_TEXT,
        "score": 67,
        "items": [
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
        learning_quiz, "get_chat_model", lambda: RunnableLambda(_invoke)
    )


def _patch_model_capturing(monkeypatch, *responses: str) -> list[list]:
    """与 _patch_model 相同，但记录每次模型调用收到的消息列表。"""
    queue = list(responses)
    received: list[list] = []

    def _invoke(prompt_value: object) -> AIMessage:
        messages = (
            prompt_value.to_messages()
            if hasattr(prompt_value, "to_messages")
            else list(prompt_value)  # type: ignore[arg-type]
        )
        received.append(messages)
        if not queue:
            raise AssertionError("模型调用次数超出预期")
        return AIMessage(content=queue.pop(0))

    monkeypatch.setattr(
        learning_quiz, "get_chat_model", lambda: RunnableLambda(_invoke)
    )
    return received


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

    assert data["status"] == learning_workflow.STATUS_WAITING_ANSWER
    assert data["run_id"]
    assert [q["question_id"] for q in data["quiz"]] == [1, 2, 3]
    # 题型归一化：未知类型降级为简答；题目数量按请求截断
    assert [q["type"] for q in data["quiz"]] == [
        "radio",
        "checkbox",
        "textarea",
    ]
    # 不向前端泄漏标准答案
    assert all("answer" not in q for q in data["quiz"])

    row = workflow_run_repo.get_for_user(data["run_id"], auth_user["id"])
    assert row is not None
    assert row["status"] == learning_workflow.STATUS_WAITING_ANSWER
    assert row["workflow_type"] == learning_workflow.WORKFLOW_TYPE_LEARNING_QUIZ
    assert row["state_json"]["quiz"] == data["quiz"]
    assert row["state_json"]["provider"] == learning_workflow.LLM_PROVIDER

    # 图停在 interrupt：checkpoint 仍在等待作答，具备恢复条件
    snapshot = learning_quiz.build_learning_quiz_graph().get_state(
        build_thread_config(data["run_id"])
    )
    assert snapshot.next == ("wait_user_answer",)
    assert snapshot.values["quiz"] == data["quiz"]

    # 出题后写入会话消息：前端凭 response_payload 渲染表单
    message = message_repo.get_by_request_id(
        f"{data['run_id']}:quiz", auth_user["id"]
    )
    assert message is not None
    assert message["request_text"] == "测一下 Python 基础"
    assert message["response_text"] == learning_workflow.QUIZ_MESSAGE_TEXT
    assert message["response_payload"] == data["quiz"]
    assert message["select_mode"] == learning_workflow.QUIZ_MESSAGE_SELECT_MODE
    assert message["status"] == 1


async def test_start_recovers_from_transient_model_failure(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    monkeypatch,
) -> None:
    """首次输出非法 → 自动重试，第二次成功即正常出题，用户无感。"""
    session = _new_session(auth_user["id"])
    _patch_model(monkeypatch, "抱歉，我无法出题", QUIZ_JSON)

    data = await _start(client, auth_headers, session["id"])

    assert data["status"] == learning_workflow.STATUS_WAITING_ANSWER
    assert [q["question_id"] for q in data["quiz"]] == [1, 2, 3]
    row = workflow_run_repo.get_for_user(data["run_id"], auth_user["id"])
    assert row["status"] == learning_workflow.STATUS_WAITING_ANSWER
    assert row["error_message"] is None


@pytest.mark.parametrize(
    ("request_text", "expected"),
    [
        ("帮我出 3 道 Python 基础题", 3),
        ("来两道 Python 题", 2),
        ("出十道题", 10),
        ("出 12 道题", 12),
        ("出几道题", None),
        ("你好，介绍一下你自己", None),
        ("出 30 道题", 20),
    ],
)
def test_infer_question_count(request_text: str, expected: int | None) -> None:
    """从口语化需求中提取题量；未提及 / 非数量词返回 None，超上限收敛到 20。"""
    assert learning_workflow.infer_question_count(request_text) == expected


async def test_start_infers_question_count_from_request_text(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    monkeypatch,
) -> None:
    """未传 question_count 时按原话提取，避免「出 3 道」被默认成 5 道。"""
    session = _new_session(auth_user["id"])
    _patch_model(monkeypatch, QUIZ_JSON)

    resp = await client.post(
        "/api/learning-workflows/start",
        headers=auth_headers,
        json={
            "session_id": session["id"],
            "request_text": "帮我出 3 道 Python 基础题",
        },
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert len(data["quiz"]) == 3
    row = workflow_run_repo.get_for_user(data["run_id"], auth_user["id"])
    assert row is not None
    assert row["state_json"]["question_count"] == 3


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
    """模型输出非 JSON → 重试耗尽后 502，记录失败节点与原因。"""
    session = _new_session(auth_user["id"])
    # 默认执行 2 次（首次 + 重试），两次都返回非法输出才会彻底失败
    _patch_model(monkeypatch, "抱歉，我无法出题", "抱歉，我无法出题")

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
    assert row.state_json["error_node"] == "generate_quiz"
    assert "generate_quiz" in row.state_json["error_message"]


async def test_submit_rejects_expired_checkpoint(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    monkeypatch,
) -> None:
    """checkpoint 丢失（模拟服务重启）→ 409，行置 failed，且不会重新调用模型。"""
    session = _new_session(auth_user["id"])
    _patch_model(monkeypatch, QUIZ_JSON)  # 仅出题一次，评分阶段不应有模型调用
    started = await _start(client, auth_headers, session["id"])

    get_workflow_checkpointer().delete_thread(started["run_id"])

    resp = await client.post(
        f"/api/learning-workflows/{started['run_id']}/submit",
        headers=auth_headers,
        json={
            "answers": [
                {"question_id": 1, "value": "A"},
                {"question_id": 2, "value": ["A"]},
                {"question_id": 3, "value": "加速查询"},
            ]
        },
    )

    assert resp.status_code == 409
    assert "已失效" in resp.json()["message"]

    row = workflow_run_repo.get_for_user(started["run_id"], auth_user["id"])
    assert row["status"] == learning_workflow.STATUS_FAILED
    assert "checkpoint" in row["error_message"]


async def test_submit_marks_failed_on_invalid_evaluation(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    monkeypatch,
) -> None:
    """评分阶段模型输出非 JSON → 重试耗尽后 502，记录失败节点。"""
    session = _new_session(auth_user["id"])
    _patch_model(monkeypatch, QUIZ_JSON, "评分失败", "评分失败")
    started = await _start(client, auth_headers, session["id"])

    resp = await client.post(
        f"/api/learning-workflows/{started['run_id']}/submit",
        headers=auth_headers,
        json={
            "answers": [
                {"question_id": 1, "value": "A"},
                {"question_id": 2, "value": ["A"]},
                {"question_id": 3, "value": "加速查询"},
            ]
        },
    )

    assert resp.status_code == 502
    row = workflow_run_repo.get_for_user(started["run_id"], auth_user["id"])
    assert row["status"] == learning_workflow.STATUS_FAILED
    assert "JSON" in (row["error_message"] or "")
    assert row["state_json"]["error_node"] == "evaluate_answer"


@pytest.mark.parametrize(
    ("weaknesses", "next_agent", "confidence"),
    [
        (["数据库选型"], "difficulty_learner", 0.9),
        ([], None, 0.4),
    ],
)
def test_finalize_result_builds_a2a_envelope(
    weaknesses: list[str], next_agent: str | None, confidence: float
) -> None:
    """有薄弱点才建议转难点学习；无薄弱点时置信度降低且流程结束。"""
    result = learning_quiz.finalize_result(
        {"score": 67, "weaknesses": weaknesses}
    )

    assert result["status"] == learning_workflow.STATUS_COMPLETED
    assert result["a2a_envelope"] == {
        "from_agent": "learning_evaluator",
        "payload_type": "weak_points",
        "payload": {"score": 67, "weaknesses": weaknesses},
        "next_agent": next_agent,
        "confidence": confidence,
    }


@pytest.mark.parametrize(
    ("from_agent", "target", "confidence", "expected"),
    [
        ("learning_evaluator", "difficulty_learner", 0.9, "difficulty_learner"),
        ("learning_evaluator", "note_archiver", 0.6, "note_archiver"),
        ("learning_evaluator", "difficulty_learner", 0.59, None),
        ("learning_evaluator", "interview_host", 0.9, None),
        ("unknown_agent", "difficulty_learner", 0.9, None),
        ("learning_evaluator", None, 0.9, None),
    ],
)
def test_decide_next_agent_whitelist(
    from_agent: str,
    target: str | None,
    confidence: float,
    expected: str | None,
) -> None:
    """只有置信度达标且命中白名单的下一跳才放行，其余一律结束流程。"""
    envelope = A2AEnvelope(
        from_agent=from_agent,
        payload_type="weak_points",
        confidence=confidence,
        next_agent=target,
    )

    assert decide_next_agent(envelope) == expected


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
    assert data["next_agent"] == "difficulty_learner"

    row = workflow_run_repo.get_for_user(started["run_id"], auth_user["id"])
    assert row["status"] == learning_workflow.STATUS_COMPLETED
    assert isinstance(row["completed_at"], int)
    assert row["state_json"]["answers"] == answers
    assert row["state_json"]["score"] == 67
    assert row["state_json"]["next_agent"] == "difficulty_learner"
    envelope = row["state_json"]["a2a_envelope"]
    assert envelope["from_agent"] == "learning_evaluator"
    assert envelope["payload_type"] == "weak_points"
    assert envelope["next_agent"] == "difficulty_learner"
    assert envelope["confidence"] == 0.9
    assert envelope["payload"]["score"] == 67

    # 评分后复用出题那条消息：正文切换为点评，载荷清空，不新增消息
    message = message_repo.get_by_request_id(
        f"{started['run_id']}:quiz", auth_user["id"]
    )
    assert message["response_text"] == EVAL_DISPLAY_TEXT
    assert message["response_payload"] is None
    assert message["status"] == 1
    assert message_repo.count_by_session(session["id"]) == 1

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
            "status": learning_workflow.STATUS_WAITING_ANSWER,
            "state_json": {
                "quiz": [],
                "status": learning_workflow.STATUS_WAITING_ANSWER,
            },
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
    assert data["status"] == learning_workflow.STATUS_WAITING_ANSWER
    assert data["state"]["request_text"] == "测一下 Python 基础"
    assert data["state"]["quiz"] == started["quiz"]
    assert data["next_agent"] is None


async def test_start_uses_dynamic_prompt(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    monkeypatch,
) -> None:
    """出题系统提示词 = 动态模板 + 静态 JSON 契约。"""
    session = _new_session(auth_user["id"])
    received = _patch_model_capturing(monkeypatch, QUIZ_JSON)
    monkeypatch.setattr(
        learning_quiz.prompt_template_service,
        "get_rendered_prompt",
        lambda agent_name, scene, user_id=None: f"动态模板：{agent_name}/{scene}",
    )

    await _start(client, auth_headers, session["id"])

    system = received[0][0]
    assert "动态模板：quiz_generate/quiz" in system.content
    # 静态契约必须追加在模板之后，约束 JSON 结构与题型
    assert '"questions"' in system.content
    assert "radio" in system.content
    assert "checkbox" in system.content
    assert "textarea" in system.content


async def test_start_falls_back_when_prompt_template_unavailable(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    monkeypatch,
) -> None:
    """提示词读取异常时降级为内置角色说明，出题仍成功。"""

    def _boom(*_: object, **__: object) -> str:
        raise RuntimeError("模板服务不可用")

    session = _new_session(auth_user["id"])
    received = _patch_model_capturing(monkeypatch, QUIZ_JSON)
    monkeypatch.setattr(
        learning_quiz.prompt_template_service, "get_rendered_prompt", _boom
    )

    data = await _start(client, auth_headers, session["id"])

    assert data["status"] == learning_workflow.STATUS_WAITING_ANSWER
    system = received[0][0]
    assert learning_quiz.DEFAULT_QUIZ_ROLE in system.content
    assert '"questions"' in system.content


async def test_submit_falls_back_to_composed_display_text(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    monkeypatch,
) -> None:
    """评分输出缺少 display_text 时，用得分 + 逐题点评 + 建议拼接兜底。"""
    eval_json = json.dumps(
        {
            "score": 0,
            "items": [
                {"question_id": 1, "correct": False, "comment": "404 表示未找到"},
                {"question_id": 2, "correct": False, "comment": "Redis 非关系型"},
                {"question_id": 3, "correct": False, "comment": "索引用于加速查询"},
            ],
            "weaknesses": ["HTTP 状态码", "索引原理"],
            "review": "建议先复习基础概念。",
        },
        ensure_ascii=False,
    )
    session = _new_session(auth_user["id"])
    _patch_model(monkeypatch, QUIZ_JSON, eval_json)
    started = await _start(client, auth_headers, session["id"])

    resp = await client.post(
        f"/api/learning-workflows/{started['run_id']}/submit",
        headers=auth_headers,
        json={
            "answers": [
                {"question_id": 1, "value": "A"},
                {"question_id": 2, "value": ["A"]},
                {"question_id": 3, "value": "加速查询"},
            ]
        },
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["score"] == 0
    message = message_repo.get_by_request_id(
        f"{started['run_id']}:quiz", auth_user["id"]
    )
    assert "本次测评得分：0 分。" in message["response_text"]
    assert "404 表示未找到" in message["response_text"]
    assert "薄弱点：HTTP 状态码、索引原理。" in message["response_text"]
    assert "建议：建议先复习基础概念。" in message["response_text"]


async def test_messages_history_returns_payload(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    monkeypatch,
) -> None:
    """历史消息接口返回 quiz 载荷；评分后同一消息载荷清空。"""
    session = _new_session(auth_user["id"])
    _patch_model(monkeypatch, QUIZ_JSON, EVAL_JSON)
    started = await _start(client, auth_headers, session["id"])

    resp = await client.get(
        f"/api/sessions/{session['id']}/messages", headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["request_text"] == "测一下 Python 基础"
    assert items[0]["request_id"] == f"{started['run_id']}:quiz"
    assert items[0]["response_text"] == learning_workflow.QUIZ_MESSAGE_TEXT
    assert items[0]["response_payload"] == started["quiz"]

    submit = await client.post(
        f"/api/learning-workflows/{started['run_id']}/submit",
        headers=auth_headers,
        json={
            "answers": [
                {"question_id": 1, "value": "A"},
                {"question_id": 2, "value": ["A"]},
                {"question_id": 3, "value": "加速查询"},
            ]
        },
    )
    assert submit.status_code == 200, submit.text

    resp = await client.get(
        f"/api/sessions/{session['id']}/messages", headers=auth_headers
    )
    items = resp.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["request_id"] == f"{started['run_id']}:quiz"
    assert items[0]["response_text"] == EVAL_DISPLAY_TEXT
    assert items[0]["response_payload"] is None
