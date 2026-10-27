"""业务层：记忆读取服务。

把「查哪些历史、怎么裁剪、如何转成模型消息」从 chat_service 的主流程拆出：
- WorkingMemory：工作记忆，Redis 保存最近原文窗口 + 更早内容摘要，TTL 8 小时；
- InstantMemory：短期记忆，取最近 N 轮已完成消息并按字符预算裁剪（MySQL）；
- MemoryService：统一入口，读取时 Redis 优先、MySQL 兜底，写入时追加并择机总结。

术语：「时间正序」指按 created_at 从早到晚（同一秒再按 id 递增），
也就是对话实际发生的先后顺序；「倒序」则是其反向（最新 → 最旧）。
"""

import json
import logging
from collections.abc import Sequence
from typing import TypedDict

import redis
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from ..core import config
from ..core.redis_client import get_client
from ..db import message_repo
from .ai.llm import get_chat_model

logger = logging.getLogger(__name__)

__all__ = [
    "InstantMemory",
    "MemoryService",
    "WorkingMemory",
    "build_chat_history_from_rows",
    "quick_summarize",
]

# 历史注入的总字符预算：超出后从最旧的消息开始丢弃，避免撑爆模型上下文
HISTORY_CHAR_BUDGET = 12000

TRUNCATED_SUFFIX = "…（内容已截断）"

# 工作记忆：Redis key 按用户 + 会话隔离，原文窗口与摘要存在同一个 JSON 串里
WORKING_MEMORY_KEY = "memory:working:{user_id}:{session_id}"
WORKING_MEMORY_TTL = 8 * 60 * 60  # 8 小时，每次读写后自动续期
# 原文总长超过该阈值时触发总结，避免频繁调用模型
WORKING_RAW_CHAR_LIMIT = 8000
# 总结后保留最近 3 轮（6 条消息）原文，更早的内容并入摘要
WORKING_KEEP_MESSAGES = 6
# 摘要上限：提示词约束 + 代码硬截断，双重保证
SUMMARY_MAX_CHARS = 500

SUMMARY_PROMPT = """你是对话摘要助手。请把「已有摘要」和「待合并对话」压缩成一段不超过 500 字的中文摘要。
要求：
1. 保留用户目标、关键事实、结论、数字与专有名词；
2. 不编造、不推测，忽略寒暄等无关内容；
3. 只输出摘要正文，不要标题、列表符号或额外解释。"""


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


def _clean_raw(value: object) -> list[dict]:
    """过滤 Redis 中结构异常的消息，避免脏数据进入模型上下文。"""
    if not isinstance(value, list):
        return []
    return [
        {"role": item["role"], "content": item["content"]}
        for item in value
        if isinstance(item, dict)
        and item.get("role") in {"user", "assistant"}
        and isinstance(item.get("content"), str)
        and item["content"]
    ]


def _raw_char_count(raw: Sequence[dict]) -> int:
    """统计原文窗口的总字符数（只算 content，不计 JSON 结构）。"""
    return sum(len(item["content"]) for item in raw)


def _format_conversation(messages: Sequence[dict]) -> str:
    """把待总结消息拼成「用户：… / 助手：…」的纯文本。"""
    lines: list[str] = []
    for item in messages:
        content = item.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        role = "用户" if item.get("role") == "user" else "助手"
        lines.append(f"{role}：{content.strip()}")
    return "\n".join(lines)


def quick_summarize(previous_summary: str, messages: Sequence[dict]) -> str:
    """用一次模型调用合并旧摘要与更早消息，结果硬截断到 500 字。

    由 WorkingMemory 在原文超阈值时调用；失败由上层捕获并保留原文。
    """
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SUMMARY_PROMPT),
            ("human", "已有摘要：\n{summary}\n\n待合并对话：\n{conversation}"),
        ]
    )
    chain = prompt | get_chat_model() | StrOutputParser()
    result = chain.invoke(
        {
            "summary": previous_summary.strip() or "（无）",
            "conversation": _format_conversation(messages),
        }
    )
    return (result or "").strip()[:SUMMARY_MAX_CHARS]


class WorkingMemoryState(TypedDict):
    """工作记忆的 Redis 数据结构：原文窗口 + 早期内容摘要。"""

    raw: list[dict]
    summary: str


class WorkingMemory:
    """会话级工作记忆：Redis 保存原文窗口与摘要，读写后自动续期。

    所有 Redis 异常都在内部消化并返回空结构 / 忽略写入，保证主流程不受影响。
    """

    def __init__(
        self,
        user_id: int,
        session_id: int,
        *,
        client: redis.Redis | None = None,
        ttl: int = WORKING_MEMORY_TTL,
    ) -> None:
        self.user_id = user_id
        self.session_id = session_id
        self.ttl = ttl
        # client 仅供测试注入；None 时使用全局懒加载单例
        self._client = client

    @property
    def key(self) -> str:
        """按用户 + 会话隔离，避免不同会话串用记忆。"""
        return WORKING_MEMORY_KEY.format(
            user_id=self.user_id, session_id=self.session_id
        )

    def _redis(self) -> redis.Redis:
        if self._client is None:
            self._client = get_client()
        return self._client

    def get(self) -> WorkingMemoryState:
        """读取原文窗口与摘要；无数据或异常时返回空结构，读到数据后自动续期。"""
        empty: WorkingMemoryState = {"raw": [], "summary": ""}
        try:
            client = self._redis()
            payload = client.get(self.key)
            if not payload:
                return empty
            # 每次成功读取都续期：活跃会话的工作记忆不会在对话中途过期
            client.expire(self.key, self.ttl)
            data = json.loads(payload)
        except Exception:
            # Redis 故障降级为 MySQL 历史，不阻断对话
            logger.warning(
                "读取工作记忆失败，降级为 MySQL 历史 | user_id=%s session_id=%s",
                self.user_id,
                self.session_id,
                exc_info=True,
            )
            return empty

        if not isinstance(data, dict):
            return empty
        summary = data.get("summary")
        return {
            "raw": _clean_raw(data.get("raw")),
            "summary": summary if isinstance(summary, str) else "",
        }

    def append_turn(self, user_text: str, ai_text: str) -> None:
        """追加一轮问答；原文超过阈值时同步总结更早内容并只保留最近 6 条。"""
        state = self.get()
        raw = [
            *state["raw"],
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": ai_text},
        ]
        summary = state["summary"]

        if _raw_char_count(raw) > WORKING_RAW_CHAR_LIMIT:
            # raw 按时间正序（最旧 → 最新）：[:-6] 是最后 6 条之外的更早消息，
            # 交给总结并入摘要；[-6:] 是最近 6 条原文，总结后继续保留。
            older = raw[:-WORKING_KEEP_MESSAGES]
            keep = raw[-WORKING_KEEP_MESSAGES:]
            try:
                new_summary = quick_summarize(summary, older)
                if not new_summary:
                    raise ValueError("摘要结果为空")
            except Exception:
                # 总结失败时保留完整原文，避免丢上下文；下一轮会再次尝试
                logger.warning(
                    "工作记忆总结失败，暂不裁剪 | user_id=%s session_id=%s",
                    self.user_id,
                    self.session_id,
                    exc_info=True,
                )
            else:
                raw = keep
                summary = new_summary

        self._save(raw, summary)

    def seed(self, messages: Sequence[BaseMessage]) -> None:
        """冷启动：把 MySQL 回退历史写入 Redis（只有原文，摘要为空）。

        不回填的话，本轮结束后 append_turn 只会把当前一问一答写进 Redis，
        下一轮就丢失了 MySQL 中的更早上下文。
        """
        raw: list[dict] = []
        for message in messages:
            content = message.content if isinstance(message.content, str) else ""
            if not content:
                continue
            role = "user" if isinstance(message, HumanMessage) else "assistant"
            raw.append({"role": role, "content": content})
        if raw:
            self._save(raw, "")

    def _save(self, raw: Sequence[dict], summary: str) -> None:
        """写回原文窗口与摘要，并刷新 TTL；失败只记日志。"""
        payload = json.dumps(
            {"raw": list(raw), "summary": summary}, ensure_ascii=False
        )
        try:
            self._redis().set(self.key, payload, ex=self.ttl)
        except Exception:
            logger.warning(
                "写入工作记忆失败 | user_id=%s session_id=%s",
                self.user_id,
                self.session_id,
                exc_info=True,
            )


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


def _build_working_history(raw: Sequence[dict]) -> list[BaseMessage]:
    """把工作记忆的原文窗口转成 LangChain 消息，保持时间正序。"""
    history: list[BaseMessage] = []
    for item in raw:
        content = item["content"]
        if item["role"] == "user":
            history.append(HumanMessage(content=content))
        else:
            history.append(AIMessage(content=content))
    return history


class MemoryService:
    """记忆统一入口：工作记忆（Redis）优先，短期记忆（MySQL）兜底。"""

    def __init__(
        self,
        instant: InstantMemory | None = None,
        *,
        redis_client: redis.Redis | None = None,
    ) -> None:
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
        # redis_client 同理：仅测试注入假客户端时非 None，生产走全局单例
        self._redis = redis_client

    def _working(self, user_id: int, session_id: int) -> WorkingMemory:
        return WorkingMemory(user_id, session_id, client=self._redis)

    def load_context(
        self, user_id: int, session_id: int, user_text: str
    ) -> dict:
        """构造链路入参：Redis 工作记忆优先，缺失时回退 MySQL 历史。

        返回 `{history, input}`：history 为时间正序消息，input 为当前问题
        （存在摘要时，摘要作为本轮问题前缀注入，避免向历史插入额外 system 消息）。
        """
        working = self._working(user_id, session_id)
        state = working.get()
        raw = state["raw"]
        summary = state["summary"]

        if raw:
            history = _build_working_history(raw)
        else:
            history = self._instant.load(session_id)
            # 冷启动回填：让后续轮次在 MySQL 历史基础上继续追加，而不是从零开始
            if history:
                working.seed(history)

        input_text = user_text
        if raw and summary:
            input_text = f"【会话摘要】\n{summary}\n\n{user_text}"
        return {"history": history, "input": input_text}

    def append_turn(
        self, user_id: int, session_id: int, user_text: str, ai_text: str
    ) -> None:
        """AI 回复成功后追加到工作记忆；Redis / 总结失败只降级，不影响回复。"""
        self._working(user_id, session_id).append_turn(user_text, ai_text)
