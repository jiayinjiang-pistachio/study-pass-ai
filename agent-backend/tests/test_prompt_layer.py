"""提示词层测试：历史 SystemMessage 合并进系统提示词。"""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.services.ai.prompt_layer import merge_history_system_messages


def _contents(messages) -> list[str]:
    return [message.content for message in messages]


def test_merge_history_system_messages() -> None:
    """多个 SystemMessage 按顺序追加到 system_prompt，并从 history 移除。"""
    history = [
        SystemMessage(content="用户画像 A"),
        HumanMessage(content="问题"),
        AIMessage(content="回答"),
        SystemMessage(content="补充记忆 B"),
    ]

    remaining, system_prompt = merge_history_system_messages(history, "基础提示词")

    assert system_prompt == "基础提示词\n\n用户画像 A\n\n补充记忆 B"
    assert _contents(remaining) == ["问题", "回答"]


def test_merge_ignores_empty_system_messages() -> None:
    """空 SystemMessage 不占用提示词，也不影响历史消息。"""
    history = [SystemMessage(content="  "), HumanMessage(content="问题")]

    remaining, system_prompt = merge_history_system_messages(history, "基础提示词")

    assert system_prompt == "基础提示词"
    assert _contents(remaining) == ["问题"]


def test_merge_without_system_messages_returns_original() -> None:
    """没有 SystemMessage 时原样返回，避免无意义的对象复制。"""
    history = [HumanMessage(content="问题"), AIMessage(content="回答")]

    remaining, system_prompt = merge_history_system_messages(history, "基础提示词")

    assert remaining is history
    assert system_prompt == "基础提示词"
