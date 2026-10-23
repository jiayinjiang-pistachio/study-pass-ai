"""记忆层：从数据库读取多轮历史，构建最终上下文（Context）。

只负责「查历史 → 转 LangChain 消息 → 拼接当前问题」，不直接调用模型。
上下文只取已成功完成（status=1）的消息，避免把生成中 / 失败的空回复喂给模型。
"""

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from ...core import config
from ...db import message_repo

TRUNCATED_SUFFIX = "…（内容已截断）"


def _truncate(text: str) -> str:
    """单条消息超限时截断，避免附件全文把上下文撑爆。"""
    limit = config.MEMORY_MESSAGE_MAX_CHARS
    if limit <= 0 or len(text) <= limit:
        return text
    return text[:limit] + TRUNCATED_SUFFIX


def _human_content(row: dict) -> str:
    """用户消息正文 + 附件提取文本（列存在时才拼接），空内容返回空串。"""
    text = (row.get("request_text") or "").strip()
    extracted = (row.get("file_extracted_text") or "").strip()
    if extracted:
        text = f"{text}\n\n[附件内容]\n{extracted}" if text else extracted
    return _truncate(text)


def _load_history(session_id: int) -> list[BaseMessage]:
    """读取最近 N 轮已完成消息，转换为 Human / AI 消息列表。"""
    limit = config.MEMORY_MAX_TURNS * 2
    if limit <= 0:
        return []

    history: list[BaseMessage] = []
    for row in message_repo.list_recent_completed(session_id, limit):
        request = _human_content(row)
        response = _truncate((row.get("response_text") or "").strip())
        if request:
            history.append(HumanMessage(content=request))
        if response:
            history.append(AIMessage(content=response))
    return history


def build_context(session_id: int, user_text: str) -> dict:
    """构造链路入参：历史消息 + 当前用户问题。"""
    return {"history": _load_history(session_id), "input": user_text}
