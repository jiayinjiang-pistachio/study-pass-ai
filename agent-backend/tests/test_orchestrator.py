"""流程总控测试：路由策略、入参映射、混合响应与越权隔离。

服务层用替身替换语义分类器与工作流入口；接口层用真实 LangGraph / SSE 链路，
只把模型换成假 Runnable，不依赖真实大模型。
"""

import json

import httpx
import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from sqlalchemy import select

from app.agent.workflows import learning_quiz
from app.core.exceptions import BusinessException, SystemException
from app.db import message_repo, session_repo, workflow_run_repo
from app.db.models import WorkflowRun
from app.db.session import SessionLocal
from app.schemas.learning_workflow import LearningWorkflowStartIn
from app.schemas.orchestrator import AgentTaskStartIn
from app.services import chat_service, learning_workflow, orchestrator_service
from app.services.orchestrator_service import (
    CHAT_AGENT_NAMES,
    QUIZ_AGENT_NAME,
    WORKFLOW_ROUTE_RULES,
    OrchestratorService,
    WorkflowRouteRule,
)

QUIZ_JSON = json.dumps(
    {
        "questions": [
            {
                "type": "radio",
                "stem": "HTTP 404 表示什么？",
                "options": [{"key": "A", "text": "未找到"}, {"key": "B", "text": "成功"}],
            }
        ]
    },
    ensure_ascii=False,
)


class _FakeClassifier:
    """语义分类器替身：记录调用并返回预设结果。"""

    def __init__(self, hit: bool) -> None:
        self.hit = hit
        self.calls: list[dict] = []

    def classify_intent(self, text, examples, threshold=0.6) -> bool:
        self.calls.append(
            {"text": text, "examples": tuple(examples), "threshold": threshold}
        )
        return self.hit


def _use_classifier(monkeypatch, classifier: _FakeClassifier) -> None:
    """让 OrchestratorService 使用替身分类器。"""

    class _Stub:
        @classmethod
        def get(cls):
            return classifier

    monkeypatch.setattr(orchestrator_service, "SemanticIntentClassifier", _Stub)


class _FakeChain:
    """模拟聊天链路：按顺序产出增量文本。"""

    async def astream(self, context: dict):
        yield "你好"


def _new_session(user_id: int) -> dict:
    return session_repo.insert(
        {"user_id": user_id, "title": "总控会话", "session_mode": 0}
    )


def _patch_model(monkeypatch, text: str) -> None:
    monkeypatch.setattr(
        learning_quiz,
        "get_chat_model",
        lambda: RunnableLambda(lambda _: AIMessage(content=text)),
    )


# ---------- 服务层 ----------


def test_route_rejects_unknown_agent(monkeypatch) -> None:
    """未登记的 agent_name → 404，且不进入语义判断。"""
    classifier = _FakeClassifier(True)
    _use_classifier(monkeypatch, classifier)

    with pytest.raises(BusinessException) as exc:
        OrchestratorService().route("unknown_agent", "帮我出几道练习题")

    assert exc.value.http_status == 404
    assert classifier.calls == []


def test_route_keyword_hit_skips_semantics(monkeypatch) -> None:
    """关键词命中直接返回规则，不调用语义分类器。"""
    classifier = _FakeClassifier(True)
    _use_classifier(monkeypatch, classifier)

    rule = OrchestratorService().route(QUIZ_AGENT_NAME, "帮我出几道练习题")

    assert rule is WORKFLOW_ROUTE_RULES[QUIZ_AGENT_NAME]
    assert classifier.calls == []


def test_route_falls_back_to_semantics(monkeypatch) -> None:
    """关键词全部落空时交给语义兜底；命中则返回同一规则。"""
    classifier = _FakeClassifier(True)
    _use_classifier(monkeypatch, classifier)

    rule = OrchestratorService().route(QUIZ_AGENT_NAME, "检验一下我对数据库索引的掌握程度")

    assert rule is WORKFLOW_ROUTE_RULES[QUIZ_AGENT_NAME]
    assert classifier.calls == [
        {
            "text": "检验一下我对数据库索引的掌握程度",
            "examples": WORKFLOW_ROUTE_RULES[QUIZ_AGENT_NAME].intent_examples,
            "threshold": WORKFLOW_ROUTE_RULES[QUIZ_AGENT_NAME].intent_threshold,
        }
    ]


def test_route_returns_none_when_no_match(monkeypatch) -> None:
    """关键词与语义都未命中 → None，由路由层走通用聊天。"""
    _use_classifier(monkeypatch, _FakeClassifier(False))

    assert OrchestratorService().route(QUIZ_AGENT_NAME, "你好，介绍一下你自己") is None


@pytest.mark.parametrize("agent_name", sorted(CHAT_AGENT_NAMES))
def test_route_chat_agents_go_straight_to_chat(monkeypatch, agent_name: str) -> None:
    """已登记聊天智能体 → None，且不触发关键词 / 语义判断。"""
    classifier = _FakeClassifier(True)
    _use_classifier(monkeypatch, classifier)

    assert OrchestratorService().route(agent_name, "帮我出几道练习题") is None
    assert classifier.calls == []


def test_route_rules_use_precise_keywords() -> None:
    """规则不变量：普通规则用双字关键词且不含单字「题」；直接分发规则不再筛词。"""
    for rule in WORKFLOW_ROUTE_RULES.values():
        assert rule.workflow_type
        if rule.direct:
            assert not rule.required_keywords
            assert not rule.intent_examples
            continue
        assert rule.required_keywords
        assert rule.intent_examples
        assert all(len(keyword) >= 2 for keyword in rule.required_keywords)
        assert "题" not in rule.required_keywords
        assert 0 < rule.intent_threshold <= 1


def test_quiz_rule_threshold_avoids_greeting_false_positive() -> None:
    """回归：问候语与出题示例的相似度实测约 0.61，阈值必须高于它并保留「考考」。"""
    rule = WORKFLOW_ROUTE_RULES[QUIZ_AGENT_NAME]

    assert rule.intent_threshold >= 0.65
    assert "考考" in rule.required_keywords


def test_start_task_maps_workflow_payload(monkeypatch) -> None:
    """工作流分支：只把会话 / 问题 / 题量 / provider 传给工作流服务。"""
    captured: dict = {}

    def _fake_start(user_id: int, payload) -> dict:
        captured["user_id"] = user_id
        captured["payload"] = payload
        return {"run_id": "run-1", "status": "waiting_answer", "quiz": []}

    monkeypatch.setattr(
        orchestrator_service.learning_workflow,
        "start_learning_workflow",
        _fake_start,
    )

    payload = AgentTaskStartIn(
        agent_name=QUIZ_AGENT_NAME,
        session_id=7,
        request_text="帮我出几道练习题",
        question_count=3,
        select_mode=2,
        provider="deepseek",
        request_id="req-1",
    )

    result = OrchestratorService().start_task(42, payload)

    assert captured["user_id"] == 42
    assert isinstance(captured["payload"], LearningWorkflowStartIn)
    assert captured["payload"].session_id == 7
    assert captured["payload"].request_text == "帮我出几道练习题"
    assert captured["payload"].question_count == 3
    assert captured["payload"].provider == "deepseek"
    assert result == {
        "route": "workflow",
        "agent_name": QUIZ_AGENT_NAME,
        "workflow_type": learning_workflow.WORKFLOW_TYPE_LEARNING_QUIZ,
        "run_id": "run-1",
        "status": "waiting_answer",
        "quiz": [],
    }


def test_start_task_returns_chat_marker(monkeypatch) -> None:
    """未命中规则时只返回聊天标记，不启动工作流。"""
    monkeypatch.setattr(
        OrchestratorService, "route", lambda self, agent_name, request_text: None
    )

    def _boom(*_: object) -> dict:
        raise AssertionError("聊天分支不应启动工作流")

    monkeypatch.setattr(
        orchestrator_service.learning_workflow, "start_learning_workflow", _boom
    )

    payload = AgentTaskStartIn(
        agent_name=QUIZ_AGENT_NAME,
        session_id=1,
        request_text="你好",
    )
    assert OrchestratorService().start_task(1, payload) == {"route": "chat"}


def test_start_task_rejects_unknown_workflow_type(monkeypatch) -> None:
    """规则指向未实现的工作流类型 → 500，提示配置错误。"""
    rule = WorkflowRouteRule(
        workflow_type="unknown_workflow",
        required_keywords=("出题",),
        intent_examples=("出题",),
    )
    monkeypatch.setitem(orchestrator_service.WORKFLOW_ROUTE_RULES, "other_agent", rule)

    payload = AgentTaskStartIn(
        agent_name="other_agent", session_id=1, request_text="帮我出题"
    )
    with pytest.raises(SystemException) as exc:
        OrchestratorService().start_task(1, payload)

    assert exc.value.http_status == 500
    assert "unknown_workflow" in (exc.value.detail or "")


# ---------- 接口层 ----------


async def test_start_agent_task_routes_to_workflow(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    monkeypatch,
) -> None:
    """关键词命中 → JSON 信封，题目落库。"""
    session = _new_session(auth_user["id"])
    _patch_model(monkeypatch, QUIZ_JSON)

    resp = await client.post(
        "/api/agent/tasks/start",
        headers=auth_headers,
        json={
            "agent_name": QUIZ_AGENT_NAME,
            "session_id": session["id"],
            "request_text": "帮我出几道练习题",
            "question_count": 1,
        },
    )

    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/json")
    data = resp.json()["data"]
    assert data["route"] == "workflow"
    assert data["agent_name"] == QUIZ_AGENT_NAME
    assert data["workflow_type"] == learning_workflow.WORKFLOW_TYPE_LEARNING_QUIZ
    assert data["status"] == learning_workflow.STATUS_WAITING_ANSWER
    assert data["quiz"][0]["question_id"] == 1

    row = workflow_run_repo.get_for_user(data["run_id"], auth_user["id"])
    assert row is not None
    assert row["status"] == learning_workflow.STATUS_WAITING_ANSWER


async def test_start_agent_task_falls_back_to_chat(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    monkeypatch,
) -> None:
    """关键词 / 语义都未命中 → 同一接口返回 SSE，事件顺序与流式对话一致。"""
    session = _new_session(auth_user["id"])
    _use_classifier(monkeypatch, _FakeClassifier(False))
    monkeypatch.setattr(
        chat_service.prompt_layer,
        "build_chat_chain",
        lambda *args, **kwargs: _FakeChain(),
    )

    resp = await client.post(
        "/api/agent/tasks/start",
        headers=auth_headers,
        json={
            "agent_name": QUIZ_AGENT_NAME,
            "session_id": session["id"],
            "request_text": "你好，介绍一下你自己",
        },
    )

    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert resp.text.index("event: meta") < resp.text.index("event: delta")
    assert resp.text.index("event: delta") < resp.text.index("event: done")
    assert 'data: {"content": "你好"}' in resp.text

    messages = message_repo.list_all_by_session(session["id"])
    assert [item["request_text"] for item in messages] == ["你好，介绍一下你自己"]
    assert messages[0]["status"] == 1


async def test_start_agent_task_chat_agent_returns_sse(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    monkeypatch,
) -> None:
    """已登记聊天智能体即使带出题关键词也走 SSE，不启动工作流。"""
    session = _new_session(auth_user["id"])
    classifier = _FakeClassifier(True)
    _use_classifier(monkeypatch, classifier)
    monkeypatch.setattr(
        chat_service.prompt_layer,
        "build_chat_chain",
        lambda *args, **kwargs: _FakeChain(),
    )

    resp = await client.post(
        "/api/agent/tasks/start",
        headers=auth_headers,
        json={
            "agent_name": "difficulty_learner",
            "session_id": session["id"],
            "request_text": "帮我出几道练习题",
        },
    )

    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert "event: meta" in resp.text
    assert classifier.calls == []
    with SessionLocal() as db:
        runs = db.scalars(
            select(WorkflowRun).where(WorkflowRun.session_id == session["id"])
        ).all()
    assert runs == []


async def test_start_agent_task_rejects_unknown_agent(
    client: httpx.AsyncClient,
    auth_headers: dict,
) -> None:
    """未知 agent_name → 404。"""
    resp = await client.post(
        "/api/agent/tasks/start",
        headers=auth_headers,
        json={"agent_name": "unknown_agent", "session_id": 1, "request_text": "你好"},
    )

    assert resp.status_code == 404
    assert resp.json()["code"] == 404


async def test_start_agent_task_rejects_foreign_session(
    client: httpx.AsyncClient,
    auth_user: dict,
    other_auth: tuple[dict, dict],
    auth_headers: dict,
    monkeypatch,
) -> None:
    """他人会话 + 出题关键词 → 404，且不产生消息 / 工作流记录。"""
    other_user, _ = other_auth
    session = _new_session(other_user["id"])
    _patch_model(monkeypatch, QUIZ_JSON)

    resp = await client.post(
        "/api/agent/tasks/start",
        headers=auth_headers,
        json={
            "agent_name": QUIZ_AGENT_NAME,
            "session_id": session["id"],
            "request_text": "帮我出几道练习题",
        },
    )

    assert resp.status_code == 404
    assert message_repo.count_by_session(session["id"]) == 0
    with SessionLocal() as db:
        runs = db.scalars(
            select(WorkflowRun).where(WorkflowRun.user_id == auth_user["id"])
        ).all()
    assert runs == []
