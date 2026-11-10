"""流程总控测试：三层路由、前置数据过滤、统一 SSE 与越权隔离。

服务层用替身替换语义分类器 / 规划器 / 子工作流；接口层用真实 SSE 链路，
只把模型换成假 Runnable，不依赖真实大模型。
"""

import json

import httpx
import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app.agent.registry import (
    CHAT_AGENT,
    DIFFICULTY_AGENT,
    INTERVIEW_HOST_AGENT,
    NOTE_AGENT,
    QUIZ_AGENT,
    REQUIRE_INTERVIEW_ROOM,
    REQUIRE_NOTE_SOURCE,
    REQUIRE_RESUME,
    ROOM_INTERVIEW,
    ROOM_STUDY,
    capabilities_for_room,
)
from app.agent.workflows import learning_quiz
from app.core.exceptions import BusinessException
from app.db import message_repo, session_repo
from app.schemas.agent import AgentChatIn
from app.services import chat_service, orchestrator_service
from app.services.orchestrator_service import OrchestratorService

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

# 达到 Tier2 触发长度（>= 10 字），但不含任何任务关键词
LONG_CHAT_TEXT = "我想先了解一下这个知识点大概是什么情况"


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


def _use_planner(monkeypatch, result: dict | None) -> None:
    """替身规划器：直接返回预设 JSON 结构（None 表示降级聊天）。"""
    monkeypatch.setattr(
        orchestrator_service.FlowControllerAgent,
        "plan",
        lambda self, **_: result,
    )


class _FakeChain:
    """模拟聊天链路：按顺序产出增量文本。"""

    async def astream(self, context: dict):
        yield "你好"


def _new_session(user_id: int, session_mode: int = ROOM_STUDY) -> dict:
    return session_repo.insert(
        {"user_id": user_id, "title": "总控会话", "session_mode": session_mode}
    )


def _patch_model(monkeypatch, text: str) -> None:
    monkeypatch.setattr(
        learning_quiz,
        "get_chat_model",
        lambda: RunnableLambda(lambda _: AIMessage(content=text)),
    )


def _payload(session_id: int, text: str, **kwargs) -> AgentChatIn:
    return AgentChatIn(session_id=session_id, request_text=text, **kwargs)


# ---------- 注册表不变量 ----------


def test_registry_keywords_are_precise() -> None:
    """快筛关键词至少双字，避免「题 / 讲」这类单字误命中。"""
    for capability in capabilities_for_room(ROOM_STUDY) + capabilities_for_room(
        ROOM_INTERVIEW
    ):
        assert capability.triggers
        assert all(len(keyword) >= 2 for keyword in capability.triggers)
        assert 0 < capability.threshold <= 1


def test_registry_prerequisites() -> None:
    """面试主考官依赖面试间 + 简历；笔记依赖已完成测评或已结束面试。"""
    interview = orchestrator_service.get_capability(INTERVIEW_HOST_AGENT)
    note = orchestrator_service.get_capability(NOTE_AGENT)

    assert interview is not None and REQUIRE_INTERVIEW_ROOM in interview.requires
    assert REQUIRE_RESUME in interview.requires
    assert note is not None and REQUIRE_NOTE_SOURCE in note.requires


# ---------- 服务层：三层路由 ----------


def test_plan_explicit_preferred_agent(monkeypatch, auth_user: dict) -> None:
    """Tier0：显式快捷指令命中且前置满足 → 直接分发。"""
    session = _new_session(auth_user["id"])
    plan = OrchestratorService().plan(
        auth_user["id"],
        _payload(session["id"], "帮我准备点题目", preferred_agent=QUIZ_AGENT),
    )

    assert plan.tier == 0
    assert plan.intent == "quiz"
    assert [agent.name for agent in plan.agents] == [QUIZ_AGENT]


def test_plan_ignores_unavailable_preferred_agent(
    monkeypatch, auth_user: dict
) -> None:
    """Tier0 不适用（房间 / 前置不满足）时静默忽略，降级到后续路由。"""
    _use_classifier(monkeypatch, _FakeClassifier(False))
    session = _new_session(auth_user["id"], ROOM_STUDY)
    plan = OrchestratorService().plan(
        auth_user["id"],
        _payload(
            session["id"],
            "你好",
            preferred_agent=INTERVIEW_HOST_AGENT,
        ),
    )

    assert plan.is_chat
    assert plan.intent == "chat"


def test_plan_keyword_hit_extracts_question_count(
    monkeypatch, auth_user: dict
) -> None:
    """Tier1 关键词命中，出题题量从原话提取，不调用语义 / 规划器。"""
    classifier = _FakeClassifier(True)
    _use_classifier(monkeypatch, classifier)
    session = _new_session(auth_user["id"])

    plan = OrchestratorService().plan(
        auth_user["id"], _payload(session["id"], "来 3 道练习题")
    )

    assert plan.tier == 1
    assert plan.agents[0].slots["question_count"] == 3
    assert classifier.calls == []


def test_plan_semantic_hit(monkeypatch, auth_user: dict) -> None:
    """Tier1 关键词落空时走语义比较，命中即分发。"""
    classifier = _FakeClassifier(True)
    _use_classifier(monkeypatch, classifier)
    session = _new_session(auth_user["id"])

    plan = OrchestratorService().plan(
        auth_user["id"], _payload(session["id"], "检验一下我掌握得怎么样")
    )

    assert plan.tier == 1
    assert plan.agents[0].name == QUIZ_AGENT
    assert classifier.calls


def test_plan_short_text_skips_planner(monkeypatch, auth_user: dict) -> None:
    """快筛未命中且消息过短 → 直接聊天，不调用规划模型。"""
    _use_classifier(monkeypatch, _FakeClassifier(False))
    _use_planner(monkeypatch, {"intent": "chat"})
    session = _new_session(auth_user["id"])

    plan = OrchestratorService().plan(
        auth_user["id"], _payload(session["id"], "你好")
    )

    assert plan.is_chat
    assert plan.tier == 3


def test_plan_uses_planner_for_long_text(monkeypatch, auth_user: dict) -> None:
    """Tier2：较长且快筛未命中的消息交给规划器，命中即分发。"""
    _use_classifier(monkeypatch, _FakeClassifier(False))
    _use_planner(
        monkeypatch,
        {
            "intent": "difficulty_card",
            "confidence": 0.9,
            "reason": "用户想听讲解",
            "reply": None,
            "agents": [{"name": DIFFICULTY_AGENT, "slots": {}}],
        },
    )
    session = _new_session(auth_user["id"])

    plan = OrchestratorService().plan(
        auth_user["id"], _payload(session["id"], LONG_CHAT_TEXT)
    )

    assert plan.tier == 2
    assert plan.agents[0].name == DIFFICULTY_AGENT
    assert plan.confidence == 0.9


def test_plan_planner_result_filtered_by_prerequisites(
    monkeypatch, auth_user: dict
) -> None:
    """规划器给出前置不满足的能力（无简历的面试主考官）→ 降级聊天。"""
    _use_classifier(monkeypatch, _FakeClassifier(False))
    _use_planner(
        monkeypatch,
        {
            "intent": "interview_prepare",
            "confidence": 0.9,
            "reason": "用户想面试",
            "reply": None,
            "agents": [{"name": INTERVIEW_HOST_AGENT, "slots": {}}],
        },
    )
    session = _new_session(auth_user["id"], ROOM_INTERVIEW)

    plan = OrchestratorService().plan(
        auth_user["id"], _payload(session["id"], LONG_CHAT_TEXT)
    )

    assert plan.is_chat


def test_plan_note_without_completed_run_is_chat(
    monkeypatch, auth_user: dict
) -> None:
    """笔记能力要求会话内已有完成测评；不满足时不参与路由。"""
    _use_classifier(monkeypatch, _FakeClassifier(False))
    _use_planner(monkeypatch, None)
    session = _new_session(auth_user["id"])

    plan = OrchestratorService().plan(
        auth_user["id"], _payload(session["id"], "帮我把刚才的内容整理成笔记")
    )

    assert plan.is_chat


def test_plan_rejects_foreign_session(auth_user: dict, other_auth) -> None:
    """他人会话统一 404，不进入任何路由。"""
    other_user, _ = other_auth
    session = _new_session(other_user["id"])

    with pytest.raises(BusinessException) as exc:
        OrchestratorService().plan(
            auth_user["id"], _payload(session["id"], "帮我出题")
        )

    assert exc.value.http_status == 404


def test_plan_falls_back_to_chat_agent() -> None:
    """兜底计划固定使用注册表内的聊天能力名。"""
    plan = orchestrator_service.AgentPlan(
        session={"id": 1, "session_mode": ROOM_STUDY},
        trace_id="t",
        tier=3,
        intent="chat",
        agents=(orchestrator_service.PlannedAgent(name=CHAT_AGENT),),
    )
    assert plan.is_chat


# ---------- 接口层 ----------


async def test_agent_chat_routes_to_quiz(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    monkeypatch,
) -> None:
    """关键词命中 → 同一 SSE 接口下发 task 事件并落库测评题目。"""
    session = _new_session(auth_user["id"])
    _patch_model(monkeypatch, QUIZ_JSON)

    resp = await client.post(
        "/api/agent/chat",
        headers=auth_headers,
        json={
            "session_id": session["id"],
            "request_text": "来 3 道练习题",
            "question_count": 1,
        },
    )

    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/event-stream")
    text = resp.text
    assert text.index("event: meta") < text.index("event: agent")
    assert text.index("event: agent") < text.index("event: task")
    assert text.index("event: task") < text.index("event: done")
    assert '"kind": "quiz"' in text

    messages = message_repo.list_all_by_session(session["id"])
    assert messages and messages[0]["request_id"].endswith(":quiz")


async def test_agent_chat_falls_back_to_chat(
    client: httpx.AsyncClient,
    auth_user: dict,
    auth_headers: dict,
    monkeypatch,
) -> None:
    """无任务意图 → 同一接口返回聊天事件流，meta 带 trace_id。"""
    session = _new_session(auth_user["id"])
    monkeypatch.setattr(
        chat_service.prompt_layer,
        "build_chat_chain",
        lambda *args, **kwargs: _FakeChain(),
    )

    resp = await client.post(
        "/api/agent/chat",
        headers=auth_headers,
        json={"session_id": session["id"], "request_text": "你好"},
    )

    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert resp.text.index("event: meta") < resp.text.index("event: delta")
    assert resp.text.index("event: delta") < resp.text.index("event: done")
    assert 'data: {"content": "你好"}' in resp.text
    assert "trace_id" in resp.text

    messages = message_repo.list_all_by_session(session["id"])
    assert [item["request_text"] for item in messages] == ["你好"]
    assert messages[0]["status"] == 1


async def test_agent_chat_rejects_foreign_session(
    client: httpx.AsyncClient,
    auth_user: dict,
    other_auth,
    auth_headers: dict,
) -> None:
    """他人会话 → 建立流之前返回 404，且不产生消息。"""
    other_user, _ = other_auth
    session = _new_session(other_user["id"])

    resp = await client.post(
        "/api/agent/chat",
        headers=auth_headers,
        json={"session_id": session["id"], "request_text": "帮我出题"},
    )

    assert resp.status_code == 404
    assert resp.json()["code"] == 404
    assert message_repo.count_by_session(session["id"]) == 0


async def test_old_task_endpoint_removed(
    client: httpx.AsyncClient,
    auth_headers: dict,
) -> None:
    """旧入口已移除：POST /api/agent/tasks/start 返回 404。"""
    resp = await client.post(
        "/api/agent/tasks/start",
        headers=auth_headers,
        json={"session_id": 1, "request_text": "你好"},
    )

    assert resp.status_code == 404


async def test_capabilities_endpoint(
    client: httpx.AsyncClient,
    auth_headers: dict,
) -> None:
    """能力列表按房间下发，供前端渲染快捷按钮。"""
    resp = await client.get("/api/agent/capabilities", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    names = {item["name"] for item in resp.json()["data"]}
    assert {
        QUIZ_AGENT,
        DIFFICULTY_AGENT,
        NOTE_AGENT,
        CHAT_AGENT,
        INTERVIEW_HOST_AGENT,
    } <= names

    resp = await client.get(
        "/api/agent/capabilities",
        headers=auth_headers,
        params={"session_mode": ROOM_INTERVIEW},
    )
    names = {item["name"] for item in resp.json()["data"]}
    assert INTERVIEW_HOST_AGENT in names
    assert QUIZ_AGENT not in names
