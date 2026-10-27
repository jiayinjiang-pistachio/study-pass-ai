"""业务层：长期记忆（用户画像的读取、写入意图判断与后台更新）。

- 读取：把 `user_profiles` 中的长期字段格式化成可注入提示词的文本；
- 判断：用 fastembed 计算当前消息与「画像写入意图」示例的语义相似度；
- 写入：后台线程调用大模型抽取结构化画像，合并后写回 `user_profiles`。

外部依赖（fastembed 模型、LLM、MySQL）失败都只降级为「不写记忆」，
不向流式对话主流程抛错。
"""

import json
import logging
import math
import threading
from collections.abc import Sequence
from functools import lru_cache

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from . import profile_service
from .ai.llm import get_chat_model

logger = logging.getLogger(__name__)

# 本地小模型：中文语义相似度，首次使用时由 fastembed 下载并缓存
EMBED_MODEL = "BAAI/bge-small-zh-v1.5"
# 与任一意图示例的余弦相似度达到该值即视为画像写入意图
INTENT_THRESHOLD = 0.6
# 过短的消息（「好的」「继续」）直接跳过，避免无意义模型调用
INTENT_MIN_CHARS = 4

# 画像写入意图示例：覆盖目标、偏好、方向、面试关注点等自我描述
PROFILE_INTENT_EXAMPLES: tuple[str, ...] = (
    "我的目标岗位是后端开发工程师",
    "我希望在半年内转行做数据分析",
    "我计划今年系统学习算法和数据库",
    "我喜欢通过看视频和做项目来学习",
    "我更喜欢先看例子再理解原理",
    "我平时学习时间比较零散",
    "我面试时比较担心算法题和系统设计",
    "我希望重点准备 Java 后端方向的面试",
    "我找工作时比较看重成长空间",
    "我的薄弱点是高并发和分布式",
)

EXTRACT_PROMPT = """你是用户画像抽取助手。请从「用户提问」和「对话上下文」中提取用户本人的长期特征，
只保留用户明确表达的信息，不要推测、不要编造。

输出严格为 JSON 对象，字段如下：
{
  "learning_goal": "学习目标（字符串；本轮没有新信息则为 null）",
  "learning_style": "学习偏好（字符串；本轮没有新信息则为 null）",
  "interview_focus": ["面试重点 / 方向（输出合并后的完整列表，没有则为 []）"],
  "long_term_summary": "结合已有摘要与最新对话后的完整长期画像摘要（不超过 800 字）"
}

要求：
1. 只记录用户自己的目标、偏好、方向、关注点，忽略寒暄和一次性问题；
2. interview_focus 每项不超过 50 字，最多 10 项，去重；
3. 新信息与已有摘要冲突时以新信息为准；
4. 只输出 JSON，不要 Markdown 代码块或额外解释。"""

SUMMARY_MAX_CHARS = 2000
FIELD_MAX_CHARS = 255
FOCUS_ITEM_MAX_CHARS = 50
FOCUS_MAX_ITEMS = 10

# 后台更新需要的上下文字段，与 memory_service 的历史消息结构保持一致
Context = str | Sequence[dict]


def _clean_text(value: object, limit: int) -> str | None:
    """去空白并截断；非字符串或空串返回 None。"""
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:limit] or None


def _clean_focus(value: object) -> list[str] | None:
    """清洗面试重点数组：去空白、去重、限长、限项数。"""
    if not isinstance(value, list):
        return None
    result: list[str] = []
    for item in value:
        text = _clean_text(item, FOCUS_ITEM_MAX_CHARS)
        if text and text not in result:
            result.append(text)
        if len(result) >= FOCUS_MAX_ITEMS:
            break
    return result or None


def _parse_json_object(raw: str) -> dict:
    """从模型输出中截取第一个 JSON 对象；解析失败返回空 dict。"""
    text = (raw or "").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _extract_fields(raw: str) -> dict:
    """把模型输出转成可入库字段；只返回非空字段，避免覆盖已有值。"""
    data = _parse_json_object(raw)
    if not data:
        return {}

    fields: dict = {}
    goal = _clean_text(data.get("learning_goal"), FIELD_MAX_CHARS)
    if goal:
        fields["learning_goal"] = goal
    style = _clean_text(data.get("learning_style"), FIELD_MAX_CHARS)
    if style:
        fields["learning_style"] = style
    focus = _clean_focus(data.get("interview_focus"))
    if focus:
        fields["interview_focus"] = focus
    summary = _clean_text(data.get("long_term_summary"), SUMMARY_MAX_CHARS)
    if summary:
        fields["long_term_summary"] = summary
    return fields


def _format_context(context: Context) -> str:
    """把历史消息列表或纯文本统一成可读对话。"""
    if isinstance(context, str):
        return context.strip()
    lines: list[str] = []
    for item in context:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        role = "用户" if item.get("role") == "user" else "助手"
        lines.append(f"{role}：{content.strip()}")
    return "\n".join(lines)


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """纯 Python 余弦相似度，避免为一次比较引入额外数值依赖。"""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if not norm_a or not norm_b:
        return 0.0
    return dot / (norm_a * norm_b)


@lru_cache(maxsize=1)
def _get_embedder():
    """懒加载 fastembed 模型：不在应用启动时下载 / 初始化。"""
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=EMBED_MODEL)


def _embed_texts(texts: Sequence[str]) -> list[list[float]]:
    """批量向量化；模型返回 numpy 数组，这里转成普通 list 便于比较。"""
    return [list(map(float, vector)) for vector in _get_embedder().embed(list(texts))]


@lru_cache(maxsize=1)
def _example_vectors() -> tuple[list[float], ...]:
    """意图示例的向量只计算一次。"""
    return tuple(_embed_texts(PROFILE_INTENT_EXAMPLES))


class LongTermMemory:
    """长期记忆：画像文本读取、写入意图判断、后台画像更新。"""

    def load_memory_context(self, user_id: int) -> str:
        """读取用户画像并格式化成提示词文本；无资料或读取失败返回空串。"""
        try:
            profile = profile_service.get_profile_dict(user_id)
        except Exception:
            logger.warning(
                "读取用户画像失败，本轮跳过长期记忆 | user_id=%s",
                user_id,
                exc_info=True,
            )
            return ""
        if not profile:
            return ""

        lines: list[str] = []
        summary = _clean_text(profile.get("long_term_summary"), SUMMARY_MAX_CHARS)
        if summary:
            lines.append(f"- 长期画像：{summary}")

        target_job = _clean_text(profile.get("target_job"), FIELD_MAX_CHARS)
        if target_job:
            lines.append(f"- 目标岗位：{target_job}")

        years = profile.get("years_experience")
        if isinstance(years, int):
            text = "应届/无经验" if years == 0 else f"{years} 年"
            lines.append(f"- 工作年限：{text}")

        target_level = _clean_text(profile.get("target_level"), FIELD_MAX_CHARS)
        if target_level:
            lines.append(f"- 目标等级：{target_level}")

        for label, key in (
            ("已掌握技能", "target_skills"),
            ("薄弱点", "weak_topics"),
            ("面试重点", "interview_focus"),
        ):
            values = profile.get(key)
            if isinstance(values, list):
                joined = "、".join(
                    item.strip() for item in values if isinstance(item, str) and item.strip()
                )
                if joined:
                    lines.append(f"- {label}：{joined}")

        learning_goal = _clean_text(profile.get("learning_goal"), FIELD_MAX_CHARS)
        if learning_goal:
            lines.append(f"- 学习目标：{learning_goal}")

        learning_style = _clean_text(profile.get("learning_style"), FIELD_MAX_CHARS)
        if learning_style:
            lines.append(f"- 学习偏好：{learning_style}")

        if not lines:
            return ""
        return (
            "【用户画像】\n"
            "以下信息来自用户历史对话，回答时自然参考，不要机械复述：\n"
            + "\n".join(lines)
        )

    def should_write(self, text: str, user_id: int | None = None) -> bool:
        """判断用户消息是否在描述自己的目标 / 偏好 / 方向。

        使用语义相似度而非关键词：与任一意图示例达到阈值即命中。
        模型不可用或异常时返回 False，退化为「不更新画像」。
        """
        text = (text or "").strip()
        if len(text) < INTENT_MIN_CHARS:
            return False
        try:
            query = _embed_texts([text])[0]
            examples = _example_vectors()
        except Exception:
            logger.warning(
                "画像写入意图判断失败，本轮跳过 | user_id=%s", user_id, exc_info=True
            )
            return False
        return max(_cosine(query, example) for example in examples) >= INTENT_THRESHOLD

    def submit_profile_update_async(
        self,
        user_id: int,
        request_text: str,
        context: Context,
    ) -> None:
        """后台线程触发画像更新；立即返回，异常只记日志。"""
        thread = threading.Thread(
            target=self._safe_update,
            args=(user_id, request_text, context),
            name=f"profile-update-{user_id}",
            daemon=True,
        )
        thread.start()

    def update_profile_from_conversation(
        self,
        user_id: int,
        request_text: str,
        context: Context,
    ) -> dict | None:
        """同步执行一次画像抽取与写库；供后台线程调用，也便于测试。"""
        profile = profile_service.get_profile_dict(user_id) or {}
        existing = json.dumps(
            {
                "learning_goal": profile.get("learning_goal"),
                "learning_style": profile.get("learning_style"),
                "interview_focus": profile.get("interview_focus"),
                "long_term_summary": profile.get("long_term_summary"),
            },
            ensure_ascii=False,
        )

        fields = _extract_fields(
            self._extract_profile_fields(existing, request_text, context)
        )
        if not fields:
            return None
        updated = profile_service.create_or_update(user_id, fields)
        logger.info(
            "长期记忆已更新 | user_id=%s fields=%s", user_id, sorted(fields)
        )
        return updated

    def _extract_profile_fields(
        self,
        existing: str,
        request_text: str,
        context: Context,
    ) -> str:
        """调用模型抽取画像字段；单独成方法便于测试替换模型。"""
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", EXTRACT_PROMPT),
                (
                    "human",
                    "已有画像：\n{existing}\n\n用户提问：\n{request_text}\n\n"
                    "对话上下文：\n{context}",
                ),
            ]
        )
        chain = prompt | get_chat_model() | StrOutputParser()
        return chain.invoke(
            {
                "existing": existing,
                "request_text": request_text.strip(),
                "context": _format_context(context) or "（无）",
            }
        ) or ""

    def _safe_update(
        self,
        user_id: int,
        request_text: str,
        context: Context,
    ) -> None:
        """后台线程入口：吞掉所有异常，避免线程内异常影响主流程。"""
        try:
            self.update_profile_from_conversation(user_id, request_text, context)
        except Exception:
            logger.warning(
                "长期记忆更新失败 | user_id=%s", user_id, exc_info=True
            )
