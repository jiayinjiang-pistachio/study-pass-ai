"""限流核心测试：真实 IP 提取、身份维度、Lua 原子计数与降级。

不依赖真实 Redis：Redis 路径用替身记录 eval 入参，降级路径用抛错替身模拟故障。
"""

import logging

import pytest
from starlette.requests import Request

from app.core import rate_limit
from app.core.exceptions import BusinessException
from app.core.security import create_access_token


def _request(
    *,
    xff: str | None = None,
    client: str = "10.0.0.1",
    authorization: str | None = None,
) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if xff is not None:
        headers.append((b"x-forwarded-for", xff.encode("utf-8")))
    if authorization is not None:
        headers.append((b"authorization", authorization.encode("utf-8")))
    return Request(
        {"type": "http", "method": "POST", "path": "/", "headers": headers,
         "client": (client, 1234)}
    )


def test_client_ip_takes_rightmost_xff() -> None:
    """只信最右侧一项；客户端伪造的左侧内容不参与取址。"""
    assert rate_limit.client_ip(_request(xff="6.6.6.6, 203.0.113.9")) == "203.0.113.9"
    assert (
        rate_limit.client_ip(_request(xff="1.1.1.1, 2.2.2.2, 203.0.113.9"))
        == "203.0.113.9"
    )


def test_client_ip_normalizes_port_and_ipv6() -> None:
    """兼容 IPv4:port / [IPv6]:port，IPv6 归一化为标准写法。"""
    assert rate_limit.client_ip(_request(xff="203.0.113.9:54321")) == "203.0.113.9"
    assert rate_limit.client_ip(_request(xff="[2001:db8::1]:443")) == "2001:db8::1"
    assert rate_limit.client_ip(_request(xff="2001:db8::2")) == "2001:db8::2"


def test_client_ip_falls_back_when_rightmost_invalid() -> None:
    """最右侧非法时不回退到可伪造的左侧，而是用直连地址。"""
    req = _request(xff="203.0.113.9, not-an-ip", client="10.0.0.7")
    assert rate_limit.client_ip(req) == "10.0.0.7"
    assert rate_limit.client_ip(_request(client="10.0.0.8")) == "10.0.0.8"


def test_identity_prefers_user_id() -> None:
    """有效访问令牌按 user_id 限流，同一账号跨 IP 共享配额。"""
    token = create_access_token(42)
    req = _request(xff="203.0.113.9", authorization=f"Bearer {token}")

    assert rate_limit._identity(req) == "user:42"


def test_identity_falls_back_to_ip_for_guest_or_bad_token() -> None:
    """无令牌 / 令牌非法（含刷新令牌）都按真实 IP 处理，不代替鉴权报 401。"""
    guest = _request(xff="203.0.113.9")
    assert rate_limit._identity(guest) == "ip:203.0.113.9"

    bad = _request(xff="203.0.113.9", authorization="Bearer not-a-jwt")
    assert rate_limit._identity(bad) == "ip:203.0.113.9"


def test_redis_increment_uses_atomic_script(monkeypatch) -> None:
    """Redis 路径：单次 eval 携带 INCR + 首次 EXPIRE 脚本与窗口参数。"""
    calls: list[tuple] = []

    class FakeRedis:
        def eval(self, script, numkeys, key, window):  # noqa: ANN001
            calls.append((script, numkeys, key, window))
            return [3, 42]

    monkeypatch.setattr(rate_limit, "RATE_LIMIT_BACKEND", "redis")
    monkeypatch.setattr(rate_limit.redis_client, "get_client", lambda: FakeRedis())

    count = rate_limit._increment("chat", "user:42", 60)

    assert count == 3
    script, numkeys, key, window = calls[0]
    assert numkeys == 1
    assert key == "ratelimit:chat:user:42"
    assert window == 60
    assert "INCR" in script and "EXPIRE" in script
    assert "current == 1" in script  # 仅首次创建 key 时设过期


def test_redis_failure_degrades_and_logs_once(monkeypatch, caplog) -> None:
    """Redis 异常自动降级本地计数，且同一间隔内只告警一次。"""
    class BrokenRedis:
        def eval(self, *_args, **_kwargs):
            raise ConnectionError("redis down")

    monkeypatch.setattr(rate_limit, "RATE_LIMIT_BACKEND", "redis")
    monkeypatch.setattr(rate_limit.redis_client, "get_client", lambda: BrokenRedis())
    caplog.set_level(logging.WARNING, logger="app.core.rate_limit")

    counts = [rate_limit._increment("chat", "ip:203.0.113.9", 60) for _ in range(3)]

    assert counts == [1, 2, 3]
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "降级" in warnings[0].getMessage()


def test_limit_raises_429_after_quota(monkeypatch) -> None:
    """固定窗口内前 N 次放行，第 N+1 次抛 429 业务异常。"""
    monkeypatch.setattr(rate_limit, "RATE_LIMIT_BACKEND", "memory")
    req = _request(xff="203.0.113.9")

    for _ in range(rate_limit.MAX_REQUESTS):
        rate_limit.enforce_register_limit(req)

    with pytest.raises(BusinessException) as exc:
        rate_limit.enforce_register_limit(req)

    assert exc.value.http_status == 429
    assert "scope=register" in exc.value.detail
    assert "ip:203.0.113.9" in exc.value.detail


def test_user_quota_isolated_from_guest_quota(monkeypatch) -> None:
    """登录用户耗尽配额不影响同 IP 游客，身份维度相互独立。"""
    monkeypatch.setattr(rate_limit, "RATE_LIMIT_BACKEND", "memory")
    user_req = _request(
        xff="203.0.113.9", authorization=f"Bearer {create_access_token(7)}"
    )
    guest_req = _request(xff="203.0.113.9")

    for _ in range(rate_limit.MAX_REQUESTS):
        rate_limit.enforce_register_limit(user_req)
    with pytest.raises(BusinessException):
        rate_limit.enforce_register_limit(user_req)

    rate_limit.enforce_register_limit(guest_req)  # 游客仍有一次配额
