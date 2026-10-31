"""A2A 统一派发测试：校验、handler 路由与 pending 降级。"""

from app.services.a2a_handoff_service import (
    HANDLERS,
    A2AHandoffService,
)
from app.services.orchestrator_service import OrchestratorService


def _envelope(
    *, from_agent: str = "learning_evaluator", target: str | None = "note_archiver",
    confidence: float = 0.9,
) -> dict:
    return {
        "from_agent": from_agent,
        "payload_type": "weak_points",
        "payload": {"score": 80, "weaknesses": []},
        "next_agent": target,
        "confidence": confidence,
    }


def test_dispatch_rejects_missing_envelope() -> None:
    """没有信封 → rejected，不抛异常。"""
    result = A2AHandoffService().dispatch(None, context={})
    assert result["status"] == "rejected"
    assert result["next_agent"] is None


def test_dispatch_rejects_invalid_envelope() -> None:
    """信封字段非法 → rejected。"""
    result = A2AHandoffService().dispatch({"from_agent": "x"}, context={})
    assert result["status"] == "rejected"
    assert "格式非法" in result["reason"]


def test_dispatch_rejects_when_dispatcher_denies() -> None:
    """置信度不足 → rejected。"""
    result = A2AHandoffService().dispatch(_envelope(confidence=0.4), context={})
    assert result["status"] == "rejected"
    assert result["next_agent"] is None


def test_dispatch_pending_when_handler_missing(monkeypatch) -> None:
    """校验通过但下游未实现 → pending，不阻断上游。"""
    monkeypatch.delitem(HANDLERS, "note_archiver", raising=False)
    result = A2AHandoffService().dispatch(_envelope(), context={"user_id": 1})
    assert result == {
        "status": "pending",
        "from_agent": "learning_evaluator",
        "next_agent": "note_archiver",
        "result": None,
        "reason": "note_archiver handler 未实现",
    }


def test_dispatch_runs_registered_handler(monkeypatch) -> None:
    """已注册 handler → completed，并透传上下文与信封。"""
    captured: dict = {}

    def handler(envelope, context):
        captured["from_agent"] = envelope.from_agent
        captured["context"] = context
        return {"archived": True}

    monkeypatch.setitem(HANDLERS, "note_archiver", handler)
    result = A2AHandoffService().dispatch(
        _envelope(), context={"user_id": 7, "run_id": "r-1"}
    )

    assert result["status"] == "completed"
    assert result["result"] == {"archived": True}
    assert captured == {
        "from_agent": "learning_evaluator",
        "context": {"user_id": 7, "run_id": "r-1"},
    }


def test_dispatch_marks_failed_when_handler_raises(monkeypatch) -> None:
    """handler 异常 → failed，错误不外泄到上游提交结果。"""

    def handler(envelope, context):
        raise RuntimeError("归档失败")

    monkeypatch.setitem(HANDLERS, "note_archiver", handler)
    result = A2AHandoffService().dispatch(_envelope(), context={})

    assert result["status"] == "failed"
    assert result["next_agent"] == "note_archiver"
    assert result["reason"] == "下游 handler 执行失败"


def test_orchestrator_delegates_to_handoff_service(monkeypatch) -> None:
    """总控只触发统一派发入口，并透传用户 / 运行 / 会话上下文。"""
    captured: dict = {}

    def handler(envelope, context):
        captured.update(context)
        return {}

    monkeypatch.setitem(HANDLERS, "note_archiver", handler)
    result = OrchestratorService().dispatch_handoff(
        _envelope(), user_id=3, run_id="run-3", session_id=9
    )

    assert result["status"] == "completed"
    assert captured == {"user_id": 3, "run_id": "run-3", "session_id": 9}
