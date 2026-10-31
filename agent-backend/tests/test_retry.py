"""通用重试工具测试：只验证重试语义，不依赖数据库与模型。"""

import pytest

from app.core.retry import RetryExhaustedError, RetryPolicy, run_with_retry


def test_run_returns_first_success() -> None:
    """首次成功不重试。"""
    calls: list[int] = []

    def action() -> str:
        calls.append(1)
        return "ok"

    assert run_with_retry(action, node="demo") == "ok"
    assert len(calls) == 1


def test_run_retries_then_succeeds() -> None:
    """瞬时失败后重试成功，默认共执行两次。"""
    calls: list[int] = []

    def action() -> str:
        calls.append(1)
        if len(calls) == 1:
            raise TimeoutError("网络抖动")
        return "ok"

    assert run_with_retry(action, node="demo") == "ok"
    assert len(calls) == 2


def test_run_exhausts_and_wraps_last_error() -> None:
    """重试耗尽抛 RetryExhaustedError，携带节点、次数与原始异常。"""
    calls: list[int] = []
    error = ValueError("模型输出非法")

    def action() -> str:
        calls.append(1)
        raise error

    with pytest.raises(RetryExhaustedError) as excinfo:
        run_with_retry(action, node="generate_quiz")

    assert len(calls) == 2
    assert excinfo.value.node == "generate_quiz"
    assert excinfo.value.attempts == 2
    assert excinfo.value.last_error is error
    assert excinfo.value.__cause__ is error
    assert "generate_quiz" in str(excinfo.value)


def test_policy_supports_custom_attempts() -> None:
    """特殊节点可通过 RetryPolicy 调整执行次数。"""
    calls: list[int] = []

    def action() -> None:
        calls.append(1)
        raise RuntimeError("boom")

    with pytest.raises(RetryExhaustedError):
        RetryPolicy(max_attempts=3).run(action, node="demo")
    assert len(calls) == 3


def test_should_retry_false_raises_original() -> None:
    """自定义判定为不可重试时立即抛原始异常，不包装。"""
    calls: list[int] = []

    def action() -> None:
        calls.append(1)
        raise RuntimeError("不可重试")

    with pytest.raises(RuntimeError):
        RetryPolicy(should_retry=lambda exc: False).run(action, node="demo")
    assert len(calls) == 1


def test_unmatched_exception_type_is_not_retried() -> None:
    """未命中 retry_on 的异常直接透传。"""
    calls: list[int] = []

    def action() -> None:
        calls.append(1)
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        RetryPolicy(retry_on=(ValueError,)).run(action, node="demo")
    assert len(calls) == 1
