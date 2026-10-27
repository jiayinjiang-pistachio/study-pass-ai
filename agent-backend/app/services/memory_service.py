"""业务层：记忆读取服务。

把「查哪些历史、怎么裁剪、如何转成模型消息」从 chat_service 的主流程拆出：
- InstantMemory：短期记忆，取最近 N 轮已完成消息并按字符预算裁剪；
- MemoryService：统一入口，后续工作记忆 / 长期记忆在此装配，调用方不受影响。

术语：「时间正序」指按 created_at 从早到晚（同一秒再按 id 递增），
也就是对话实际发生的先后顺序；「倒序」则是其反向（最新 → 最旧）。
"""

from collections.abc import Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from ..core import config
from ..db import message_repo

__all__ = ["InstantMemory", "MemoryService", "build_chat_history_from_rows"]

# 历史注入的总字符预算：超出后从最旧的消息开始丢弃，避免撑爆模型上下文
HISTORY_CHAR_BUDGET = 12000

TRUNCATED_SUFFIX = "…（内容已截断）"


def _truncate(text: str, limit: int) -> str:
    """按字符上限截断，并保证追加提示语后仍不超过上限。"""
    if not text or limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit <= len(TRUNCATED_SUFFIX):
        return text[:limit]
    return text[: limit - len(TRUNCATED_SUFFIX)] + TRUNCATED_SUFFIX


def _human_content(row: dict) -> str:
    """用户消息正文 + 附件提取文本；两者都为空时返回空串。"""
    text = (row.get("request_text") or "").strip()
    extracted = (row.get("file_extracted_text") or "").strip()
    if extracted:
        return f"{text}\n\n[附件内容]\n{extracted}" if text else extracted
    return text


def _prepare_row(row: dict) -> dict:
    """把单条消息裁剪成可直接格式化的副本。

    附件文本并入 request_text 后清空原字段，避免格式化时重复拼接；
    单条按 MEMORY_MESSAGE_MAX_CHARS 截断，防止一条超长附件吃光总预算。
    """
    request = _truncate(_human_content(row), config.MEMORY_MESSAGE_MAX_CHARS)
    response = _truncate(
        (row.get("response_text") or "").strip(), config.MEMORY_MESSAGE_MAX_CHARS
    )
    return {
        **row,
        "request_text": request,
        "response_text": response,
        "file_extracted_text": None,
    }


def _fit_char_budget(rows: Sequence[dict], budget: int) -> list[dict]:
    """按总字符预算裁剪历史，返回仍为「时间正序」（最早 → 最新）的副本。

    入参 rows 是时间正序；预算分配反过来从最新一条开始（未来消息更重要），
    放不下的旧消息整体丢弃；最新一条即使超出预算也保留并按剩余预算截断，
    保证上下文至少包含最近一轮。最终反转回时间正序，供格式化函数直接使用。
    """
    if budget <= 0:
        return []

    kept: list[dict] = []
    used = 0
    # 倒序（最新 → 最旧）分配预算，越新的消息优先级越高
    for row in reversed(rows):
        prepared = _prepare_row(row)
        request = prepared["request_text"]
        response = prepared["response_text"]
        # 一轮问答（用户消息 + AI 回复）整体占用预算
        cost = len(request) + len(response)

        remaining = budget - used
        if cost > remaining:
            if kept:
                # 已经保留了更新的消息，这条更旧的整轮直接丢弃
                break
            # 最新一轮本身就超预算：先满足用户消息，剩余预算再给 AI 回复
            request = _truncate(request, remaining)
            response = _truncate(response, remaining - len(request))
            prepared["request_text"] = request
            prepared["response_text"] = response
            cost = len(request) + len(response)

        kept.append(prepared)
        used += cost

    # 分配时是倒序，输出前反转回时间正序（最早 → 最新）
    kept.reverse()
    return kept


def build_chat_history_from_rows(rows: Sequence[dict]) -> list[BaseMessage]:
    """把消息行格式化为 LangChain 的 Human / AI 消息序列。

    输出保持时间正序：最早的一轮在最前、最新的一轮在最后，与模型看到的多轮
    对话顺序一致；当前问题由调用方接在 history 之后，不会打乱先后关系。
    """
    history: list[BaseMessage] = []
    for row in rows:
        request = _human_content(row)
        response = (row.get("response_text") or "").strip()
        if request:
            history.append(HumanMessage(content=request))
        if response:
            history.append(AIMessage(content=response))
    return history


class InstantMemory:
    """短期记忆：最近 N 轮已完成消息，按字符预算裁剪后转成模型消息。"""

    def __init__(
        self,
        *,
        max_turns: int | None = None,
        char_budget: int | None = None,
    ) -> None:
        self.max_turns = config.MEMORY_MAX_TURNS if max_turns is None else max_turns
        self.char_budget = (
            HISTORY_CHAR_BUDGET if char_budget is None else char_budget
        )

    def load(self, session_id: int) -> list[BaseMessage]:
        """读取短期记忆：查最近 N 轮 → 字符预算裁剪 → 格式化输出。"""
        if self.max_turns <= 0:
            return []

        # 仓储先按 created_at 倒序（最新 → 最旧）取最近 N 轮，再反转返回，
        # 因此这里拿到的 rows 是时间正序（最早 → 最新），即对话发生顺序
        rows = message_repo.list_recent_completed(session_id, self.max_turns)
        return build_chat_history_from_rows(_fit_char_budget(rows, self.char_budget))


class MemoryService:
    """记忆统一入口：当前只有短期记忆，工作 / 长期记忆后续在此挂载。"""

    def __init__(self, instant: InstantMemory | None = None) -> None:
        # 为什么不直接写 instant: InstantMemory = InstantMemory()：
        # 1. 默认参数在函数定义（导入模块）时就求值，会让实例提前创建、被所有调用方共享；
        #    改成运行时按需创建，每个 MemoryService 持有独立实例，后续 InstantMemory
        #    若增加连接 / 缓存等状态也不会互相串用。
        # 2. 保留注入口：测试可传入自定义轮数 / 预算的 InstantMemory（或替身），
        #    无需改全局 config；后续接入工作记忆、长期记忆时沿用同样的可选参数即可，
        #    调用方仍统一走 MemoryService。
        # 用 `is not None` 而非 `instant or ...`：只把「未传」视为缺省，
        # 不会因对象自定义了假值行为而误判。
        #
        # `instant is not None` 何时成立：仅当调用方显式传入实例。
        # - 生产：chat_service 调用 MemoryService()，不传 → 走右侧默认实例；
        # - 测试：MemoryService(InstantMemory(char_budget=10000))，传入 → 直接使用；
        # - 显式传 None 与不传等价，同样创建默认实例。
        self._instant = instant if instant is not None else InstantMemory()

    def build_context(self, session_id: int, user_text: str) -> dict:
        """构造链路入参：历史消息 + 当前问题。"""
        return {"history": self._instant.load(session_id), "input": user_text}
