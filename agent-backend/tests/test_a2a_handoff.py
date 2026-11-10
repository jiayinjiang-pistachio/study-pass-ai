"""A2A 统一派发测试：校验、handler 路由、跳数限制与幂等。"""

import pytest

from app.services.a2a_handoff_service import (
    HANDLERS,
    A2AHandoffService,
    reset_idempotency_cache,
)
from app.services.orchestrator_service import OrchestratorService


@pytest.fixture(autouse=True)
def _clear_idempotency() -> None:
    """每个用例从空缓存开始，避免用例间互相命中幂等结果。"""
    reset_idempotency_cache()


def _envelope(
    *, from_agent: str = "learning_evaluator", target: str | None = "note_archiver",
    confidence: float = 0.9, trace_id: str | None = "trace-1", hops: int = 0,
) -> dict:
    return {
        "from_agent": from_agent,
        "payload_type": "weak_points",
        "payload": {"score": 80, "weaknesses": []},
        "next_agent": target,
        "confidence": confidence,
        "trace_id": trace_id,
        "hops": hops,
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
        "trace_id": "trace-1",
        "hops": 0,
        "result_ref": None,
        "result": None,
        "reason": "note_archiver handler 未实现",
        "idempotent": False,
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
    result = OrchestratorService().dispatch_a2a_handoff(
        _envelope(), user_id=3, run_id="run-3", session_id=9
    )

    assert result["status"] == "completed"
    assert captured == {"user_id": 3, "run_id": "run-3", "session_id": 9}


class _Background:
    """BackgroundTasks 测试替身：只记录待执行任务。"""

    def __init__(self) -> None:
        self.tasks: list[tuple] = []

    def add_task(self, func, *args, **kwargs) -> None:
        self.tasks.append((func, args, kwargs))


def test_orchestrator_schedules_handoff_when_background_tasks_given(
    monkeypatch,
) -> None:
    """传 background_tasks 时只登记后台任务，返回 scheduled。"""
    captured: dict = {}

    def handler(envelope, context):
        captured.update(context)
        return {}

    monkeypatch.setitem(HANDLERS, "note_archiver", handler)
    background = _Background()

    result = OrchestratorService().dispatch_a2a_handoff(
        _envelope(),
        user_id=1,
        run_id="run-1",
        session_id=2,
        state={"status": "completed"},
        background_tasks=background,
    )

    assert result == {
        "status": "scheduled",
        "from_agent": "learning_evaluator",
        "next_agent": "note_archiver",
        "trace_id": "trace-1",
        "hops": 0,
        "result_ref": None,
        "result": None,
        "reason": "A2A 接力已转入后台执行",
        "idempotent": False,
    }
    assert captured == {}
    assert len(background.tasks) == 1

    func, args, kwargs = background.tasks[0]
    func(*args, **kwargs)
    assert captured == {
        "user_id": 1,
        "run_id": "run-1",
        "session_id": 2,
        "state": {"status": "completed"},
    }


def test_dispatch_rejects_self_loop() -> None:
    """下游指回自身 → rejected，避免同一条链路无限自循环。"""
    result = A2AHandoffService().dispatch(
        _envelope(from_agent="note_archiver", target="note_archiver"), context={}
    )
    assert result["status"] == "rejected"
    assert result["reason"] == "禁止自循环接力"


def test_dispatch_rejects_when_hops_exceeded() -> None:
    """信封已用完最大跳数 → rejected，不再继续派发。"""
    result = A2AHandoffService().dispatch(_envelope(hops=2), context={})
    assert result["status"] == "rejected"
    assert "跳数超过上限" in result["reason"]


def test_dispatch_is_idempotent_for_completed_handoff(monkeypatch) -> None:
    """同一用户 + trace + 目标重复派发时复用已完成结果，handler 只执行一次。"""
    calls: list[dict] = []

    def handler(envelope, context):
        calls.append(context)
        return {"note_id": 101}

    monkeypatch.setitem(HANDLERS, "note_archiver", handler)
    service = A2AHandoffService()

    first = service.dispatch(_envelope(), context={"user_id": 5})
    second = service.dispatch(_envelope(), context={"user_id": 5})

    assert len(calls) == 1
    assert first["status"] == "completed"
    assert first["hops"] == 1
    assert first["result_ref"] == "101"
    assert first["idempotent"] is False
    assert second["idempotent"] is True
    assert second["result"] == {"note_id": 101}


def test_dispatch_generates_trace_id_when_missing(monkeypatch) -> None:
    """信封未带 trace_id 时由派发服务生成，并在结果中回传。"""
    def handler(envelope, context):
        return {}

    monkeypatch.setitem(HANDLERS, "note_archiver", handler)
    result = A2AHandoffService().dispatch(
        _envelope(trace_id=None), context={"user_id": 6}
    )
    assert result["status"] == "completed"
    assert isinstance(result["trace_id"], str) and result["trace_id"]


def test_orchestrator_keeps_rejection_synchronous_with_background_tasks() -> None:
    """没有下一跳时无需后台，直接同步返回 rejected。"""
    background = _Background()
    result = OrchestratorService().dispatch_a2a_handoff(
        _envelope(target=None),
        user_id=1,
        run_id="run-1",
        session_id=2,
        background_tasks=background,
    )

    assert result["status"] == "rejected"
    assert background.tasks == []
