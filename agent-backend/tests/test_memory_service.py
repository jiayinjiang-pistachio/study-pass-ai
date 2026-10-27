"""短期记忆读取服务测试：轮数上限、字符预算、格式化与统一入口。"""

import uuid

from langchain_core.messages import HumanMessage

from app.core import config
from app.db import message_repo, session_repo
from app.services.memory_service import (
    InstantMemory,
    MemoryService,
    build_chat_history_from_rows,
)


def _new_session(user_id: int) -> dict:
    return session_repo.insert(
        {"user_id": user_id, "title": "记忆测试", "session_mode": 0}
    )


def _add_round(
    user_id: int,
    session_id: int,
    request: str,
    response: str,
    *,
    status: int = 1,
    extracted: str | None = None,
) -> dict:
    return message_repo.insert(
        {
            "user_id": user_id,
            "session_id": session_id,
            "select_mode": 0,
            "request_id": uuid.uuid4().hex,
            "request_text": request,
            "response_text": response,
            "file_extracted_text": extracted,
            "status": status,
        }
    )


async def test_load_keeps_only_recent_turns(auth_user: dict) -> None:
    """默认只取最近 8 轮，更早的问答不进入上下文。"""
    session = _new_session(auth_user["id"])
    for index in range(1, 11):
        _add_round(
            auth_user["id"], session["id"], f"问题{index}", f"回答{index}"
        )

    history = InstantMemory(max_turns=8, char_budget=10000).load(session["id"])

    assert len(history) == 16
    assert history[0].content == "问题3"
    assert history[-1].content == "回答10"


async def test_load_skips_unfinished_and_empty(auth_user: dict) -> None:
    """生成中、失败与空回复都不应作为历史注入。"""
    session = _new_session(auth_user["id"])
    _add_round(auth_user["id"], session["id"], "已完成", "回答")
    _add_round(auth_user["id"], session["id"], "生成中", "", status=0)
    _add_round(auth_user["id"], session["id"], "失败", "部分内容", status=2)
    _add_round(auth_user["id"], session["id"], "空回复", "", status=1)

    history = InstantMemory(char_budget=10000).load(session["id"])

    assert [message.content for message in history] == ["已完成", "回答"]


async def test_char_budget_drops_oldest_rounds(auth_user: dict) -> None:
    """总预算只够最新一轮时，更早的整轮问答被丢弃。"""
    session = _new_session(auth_user["id"])
    _add_round(auth_user["id"], session["id"], "很旧的问题", "很旧的回答")
    _add_round(auth_user["id"], session["id"], "最新问题", "最新回答")

    budget = len("最新问题") + len("最新回答")
    history = InstantMemory(char_budget=budget).load(session["id"])

    assert [message.content for message in history] == ["最新问题", "最新回答"]
    assert len("".join(message.content for message in history)) <= budget


async def test_char_budget_truncates_latest_round(auth_user: dict) -> None:
    """最新一轮本身超预算时按预算截断，而不是把上下文清空。"""
    session = _new_session(auth_user["id"])
    _add_round(
        auth_user["id"], session["id"], "一二三四五六七八九十", "一二三四五六七八九十"
    )

    history = InstantMemory(char_budget=6).load(session["id"])

    assert len(history) == 1
    assert isinstance(history[0], HumanMessage)
    assert history[0].content == "一二三四五六"


async def test_single_message_respects_max_chars(
    auth_user: dict, monkeypatch
) -> None:
    """单条消息先按 MEMORY_MESSAGE_MAX_CHARS 截断，避免吃掉全部预算。"""
    monkeypatch.setattr(config, "MEMORY_MESSAGE_MAX_CHARS", 20)
    session = _new_session(auth_user["id"])
    _add_round(auth_user["id"], session["id"], "长" * 100, "答" * 100)

    history = InstantMemory(char_budget=1000).load(session["id"])

    assert len(history) == 2
    assert all(len(message.content) <= 20 for message in history)
    assert all("内容已截断" in message.content for message in history)


async def test_load_merges_extracted_text(auth_user: dict) -> None:
    """附件提取文本拼在对应用户消息后。"""
    session = _new_session(auth_user["id"])
    _add_round(
        auth_user["id"], session["id"], "看看附件", "好的", extracted="附件正文"
    )

    history = InstantMemory(char_budget=10000).load(session["id"])

    assert history[0].content == "看看附件\n\n[附件内容]\n附件正文"
    assert history[1].content == "好的"


async def test_memory_service_builds_context(auth_user: dict) -> None:
    """统一入口返回链路所需的 history + input 结构。"""
    session = _new_session(auth_user["id"])
    _add_round(auth_user["id"], session["id"], "历史问题", "历史回答")

    context = MemoryService(
        InstantMemory(char_budget=10000)
    ).build_context(session["id"], "当前问题")

    assert context["input"] == "当前问题"
    assert [message.content for message in context["history"]] == [
        "历史问题",
        "历史回答",
    ]


def test_build_chat_history_from_rows_formats_messages() -> None:
    """空正文的消息段直接跳过，保持 Human / AI 交替顺序。"""
    history = build_chat_history_from_rows(
        [
            {"request_text": "问题1", "response_text": "回答1"},
            {"request_text": "问题2", "response_text": ""},
        ]
    )

    assert [type(message).__name__ for message in history] == [
        "HumanMessage",
        "AIMessage",
        "HumanMessage",
    ]
