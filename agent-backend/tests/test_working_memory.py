"""工作记忆测试：Redis 读写、按需总结、降级与 MySQL 回退。

用内存替身代替真实 Redis，保证用例不依赖外部服务；MySQL 侧仍走真实库
（与其余记忆用例一致），通过 auth_user 前缀数据清理。
"""

import json
import uuid

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.db import message_repo, session_repo
from app.services import memory_service
from app.services.memory_service import (
    InstantMemory,
    MemoryService,
    WorkingMemory,
)


class FakeRedis:
    """最小 Redis 替身：只实现工作记忆用到的 get / set / expire。"""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.expires: dict[str, int] = {}

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.store[key] = value
        if ex is not None:
            self.expires[key] = ex
        return True

    def expire(self, key: str, ttl: int) -> bool:
        if key not in self.store:
            return False
        self.expires[key] = ttl
        return True


@pytest.fixture
def fake_redis() -> FakeRedis:
    """每个用例独立的内存 Redis，避免状态串用。"""
    return FakeRedis()


class BrokenRedis:
    """所有操作都抛错，用于验证 Redis 故障不影响主流程。"""

    def get(self, key: str) -> None:
        raise RuntimeError("redis down")

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        raise RuntimeError("redis down")

    def expire(self, key: str, ttl: int) -> None:
        raise RuntimeError("redis down")


def _new_session(user_id: int) -> dict:
    return session_repo.insert(
        {"user_id": user_id, "title": "工作记忆测试", "session_mode": 0}
    )


def _add_round(user_id: int, session_id: int, request: str, response: str) -> dict:
    return message_repo.insert(
        {
            "user_id": user_id,
            "session_id": session_id,
            "select_mode": 0,
            "request_id": uuid.uuid4().hex,
            "request_text": request,
            "response_text": response,
            "status": 1,
        }
    )


def _seed(fake: FakeRedis, memory: WorkingMemory, raw: list[dict], summary: str = "") -> None:
    """直接写入 Redis 替身，模拟已有工作记忆。"""
    fake.store[memory.key] = json.dumps(
        {"raw": raw, "summary": summary}, ensure_ascii=False
    )


def test_get_returns_empty_when_missing() -> None:
    """Redis 无数据时返回空结构，而不是抛错。"""
    memory = WorkingMemory(1, 2, client=FakeRedis())

    assert memory.get() == {"raw": [], "summary": ""}


def test_get_renews_ttl(fake_redis: FakeRedis) -> None:
    """成功读取后续期，保证活跃会话的记忆不会中途过期。"""
    memory = WorkingMemory(1, 2, client=fake_redis)
    _seed(fake_redis, memory, [{"role": "user", "content": "你好"}])

    memory.get()

    assert fake_redis.expires[memory.key] == memory_service.WORKING_MEMORY_TTL


def test_append_turn_writes_raw_only_under_limit(fake_redis: FakeRedis) -> None:
    """未超阈值时只追加原文，摘要保持不变。"""
    memory = WorkingMemory(1, 2, client=fake_redis)
    _seed(fake_redis, memory, [{"role": "user", "content": "旧问题"}], "旧摘要")

    memory.append_turn("新问题", "新回答")

    data = json.loads(fake_redis.store[memory.key])
    assert data["summary"] == "旧摘要"
    assert data["raw"] == [
        {"role": "user", "content": "旧问题"},
        {"role": "user", "content": "新问题"},
        {"role": "assistant", "content": "新回答"},
    ]


def test_append_turn_summarizes_over_limit(
    fake_redis: FakeRedis, monkeypatch
) -> None:
    """超过字符阈值时把更早消息交给总结，只保留最近 6 条原文。"""
    monkeypatch.setattr(memory_service, "WORKING_RAW_CHAR_LIMIT", 5)
    memory = WorkingMemory(1, 2, client=fake_redis)
    raw = [
        {"role": "user" if index % 2 == 0 else "assistant", "content": f"消息{index}"}
        for index in range(8)
    ]
    _seed(fake_redis, memory, raw, "旧摘要")

    captured: dict = {}

    def _fake_summarize(previous_summary: str, messages) -> str:
        captured["previous"] = previous_summary
        captured["messages"] = list(messages)
        return "新摘要"

    monkeypatch.setattr(memory_service, "quick_summarize", _fake_summarize)

    memory.append_turn("新问题", "新回答")

    # 总结的入参 = 旧摘要 + 被裁掉的更早消息（追加后共 10 条，前 4 条并入摘要）
    assert captured["previous"] == "旧摘要"
    assert captured["messages"] == raw[:4]

    data = json.loads(fake_redis.store[memory.key])
    assert data["summary"] == "新摘要"
    assert data["raw"] == [
        *raw[4:],
        {"role": "user", "content": "新问题"},
        {"role": "assistant", "content": "新回答"},
    ]
    assert len(data["raw"]) == memory_service.WORKING_KEEP_MESSAGES


def test_summary_failure_keeps_raw(fake_redis: FakeRedis, monkeypatch) -> None:
    """总结失败时保留完整原文，避免丢上下文，下一轮会再次尝试。"""
    monkeypatch.setattr(memory_service, "WORKING_RAW_CHAR_LIMIT", 5)
    memory = WorkingMemory(1, 2, client=fake_redis)
    raw = [{"role": "user", "content": f"消息{index}"} for index in range(8)]
    _seed(fake_redis, memory, raw, "旧摘要")

    def _boom(previous_summary: str, messages) -> str:
        raise RuntimeError("模型不可用")

    monkeypatch.setattr(memory_service, "quick_summarize", _boom)

    memory.append_turn("新问题", "新回答")

    data = json.loads(fake_redis.store[memory.key])
    assert data["summary"] == "旧摘要"
    assert data["raw"] == [
        *raw,
        {"role": "user", "content": "新问题"},
        {"role": "assistant", "content": "新回答"},
    ]


def test_redis_errors_are_swallowed() -> None:
    """Redis 故障时读写都降级为空 / 忽略，不向上抛异常。"""
    memory = WorkingMemory(1, 2, client=BrokenRedis())

    assert memory.get() == {"raw": [], "summary": ""}
    memory.append_turn("问题", "回答")


def test_load_context_prefers_working_memory(
    fake_redis: FakeRedis, monkeypatch
) -> None:
    """Redis 有原文时直接使用，不查 MySQL。"""
    memory = WorkingMemory(1, 2, client=fake_redis)
    _seed(
        fake_redis,
        memory,
        [
            {"role": "user", "content": "Redis 问题"},
            {"role": "assistant", "content": "Redis 回答"},
        ],
    )

    def _unexpected(self, session_id: int):
        raise AssertionError("不应回退 MySQL")

    monkeypatch.setattr(InstantMemory, "load", _unexpected)
    service = MemoryService(InstantMemory(), redis_client=fake_redis)

    context = service.load_context(1, 2, "当前问题")

    assert [type(message) for message in context["history"]] == [
        HumanMessage,
        AIMessage,
    ]
    assert [message.content for message in context["history"]] == [
        "Redis 问题",
        "Redis 回答",
    ]
    assert context["input"] == "当前问题"


def test_load_context_falls_back_and_seeds(
    auth_user: dict, fake_redis: FakeRedis
) -> None:
    """Redis 为空时回退 MySQL，并把历史回填到 Redis 供后续轮次追加。"""
    session = _new_session(auth_user["id"])
    _add_round(auth_user["id"], session["id"], "MySQL 问题", "MySQL 回答")
    service = MemoryService(
        InstantMemory(char_budget=10000), redis_client=fake_redis
    )

    context = service.load_context(auth_user["id"], session["id"], "当前问题")

    assert [message.content for message in context["history"]] == [
        "MySQL 问题",
        "MySQL 回答",
    ]
    memory = WorkingMemory(auth_user["id"], session["id"], client=fake_redis)
    data = json.loads(fake_redis.store[memory.key])
    assert data["raw"] == [
        {"role": "user", "content": "MySQL 问题"},
        {"role": "assistant", "content": "MySQL 回答"},
    ]
    assert data["summary"] == ""


def test_load_context_injects_summary_prefix(fake_redis: FakeRedis) -> None:
    """存在摘要时作为本轮问题前缀注入，不额外插入 system 消息。"""
    memory = WorkingMemory(1, 2, client=fake_redis)
    _seed(fake_redis, memory, [{"role": "user", "content": "近期问题"}], "会话摘要")
    service = MemoryService(InstantMemory(), redis_client=fake_redis)

    context = service.load_context(1, 2, "当前问题")

    assert context["input"] == "【会话摘要】\n会话摘要\n\n当前问题"
    assert [message.content for message in context["history"]] == ["近期问题"]


class _StubLongTerm:
    """长期记忆替身：只记录读取调用并返回固定画像文本。"""

    def __init__(self, text: str = "") -> None:
        self.text = text
        self.calls: list[int] = []

    def load_memory_context(self, user_id: int) -> str:
        self.calls.append(user_id)
        return self.text


def test_load_context_prepends_long_term_system_message(
    fake_redis: FakeRedis,
) -> None:
    """画像文本作为 SystemMessage 插在 history 最前。"""
    stub = _StubLongTerm("【用户画像】\n- 学习目标：转行后端")
    service = MemoryService(
        InstantMemory(), redis_client=fake_redis, long_term=stub
    )

    context = service.load_context(1, 2, "当前问题")

    assert isinstance(context["history"][0], SystemMessage)
    assert context["history"][0].content == "【用户画像】\n- 学习目标：转行后端"
    assert stub.calls == [1]


def test_load_context_can_disable_long_term(fake_redis: FakeRedis) -> None:
    """enable_long_term=False 时不读画像，也不注入 SystemMessage。"""
    stub = _StubLongTerm("【用户画像】\n- 学习目标：转行后端")
    service = MemoryService(
        InstantMemory(), redis_client=fake_redis, long_term=stub
    )

    context = service.load_context(1, 2, "当前问题", enable_long_term=False)

    assert context["history"] == []
    assert stub.calls == []


def test_long_term_message_is_not_seeded_to_redis(
    auth_user: dict, fake_redis: FakeRedis
) -> None:
    """冷启动回填只写 MySQL 历史，画像 SystemMessage 不进入工作记忆。"""
    session = _new_session(auth_user["id"])
    _add_round(auth_user["id"], session["id"], "历史问题", "历史回答")
    stub = _StubLongTerm("【用户画像】\n- 学习目标：转行后端")
    service = MemoryService(
        InstantMemory(char_budget=10000), redis_client=fake_redis, long_term=stub
    )

    service.load_context(auth_user["id"], session["id"], "当前问题")

    memory = WorkingMemory(auth_user["id"], session["id"], client=fake_redis)
    data = json.loads(fake_redis.store[memory.key])
    assert data["raw"] == [
        {"role": "user", "content": "历史问题"},
        {"role": "assistant", "content": "历史回答"},
    ]
