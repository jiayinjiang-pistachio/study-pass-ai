"""流程总控规划器：只在快筛歧义时调用一次模型，输出结构化调度计划。

输出使用 JSON（与出题 / 评分一致，走 parse_json_object），不依赖 tool-calling，
兼容 DeepSeek / Qwen 等 OpenAI 兼容服务。规划器只能从注册表给定的能力中挑选，
非法名称一律丢弃；超时、JSON 非法或置信度不足时返回 None，由调用方降级为聊天。
"""

import json
import logging
from typing import Any

from langchain_core.messages import SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from ...services import prompt_template_service
from ...services.ai.json_utils import parse_json_object
from ...services.ai.llm import get_chat_model
from ..registry import AgentCapability

logger = logging.getLogger(__name__)

PROMPT_AGENT = "flow_controller"
PROMPT_SCENE = "workflow"
MIN_CONFIDENCE = 0.6
MAX_AGENTS = 2
MAX_TEXT_CHARS = 160

DEFAULT_ROLE = """你是学面通 AI 的流程总控。根据用户本轮消息、当前房间与会话状态，
判断应该交给哪个专业智能体处理；没有明确任务意图时交给普通聊天。"""

PLANNER_OUTPUT_RULES = """输出要求（优先于上方模板中的冲突规则）：
1. 只输出一个 JSON 对象，不要 Markdown 代码块或额外解释；
2. 字段固定为 intent / confidence / reason / reply / agents；
3. intent 取值为下列之一：chat、learning_quiz、difficulty_card、interview_prepare、note_archive；
4. confidence 为 0~1 的小数，低于 0.6 时不要强行调度；
5. agents 最多 2 个，每项形如 {"name": "<能力名>", "slots": {}}；名字只能从「可用能力」中选择；
6. 没有明确任务意图时返回 {"intent":"chat","confidence":1,"reason":"普通对话","agents":[{"name":"chat_answer","slots":{}}]}；
7. 前置数据不满足（例如面试间没有简历）时返回 chat，并在 reply 里给出可读提示；
8. 不要编造未提供的会话数据。"""


def _format_capabilities(capabilities: tuple[AgentCapability, ...]) -> str:
    """把注册表里的能力压缩成规划提示词里的一段清单。"""
    lines = ["chat_answer（普通聊天，任何房间可用）"]
    for capability in capabilities:
        requires = "、".join(capability.requires) or "无"
        lines.append(
            f"{capability.name}（{capability.title}）：{capability.description}"
            f" 前置={requires} 产物={capability.returns}"
        )
    return "\n".join(lines)


def _format_history(history: list[dict], limit: int = 4) -> str:
    """最近几轮对话摘要，帮助区分「继续」与新任务。"""
    parts: list[str] = []
    for item in history[-limit:]:
        role = "用户" if item.get("role") == "user" else "助手"
        content = str(item.get("content") or "").strip()
        if content:
            parts.append(f"{role}：{content[:200]}")
    return "\n".join(parts) or "（无）"


def _build_system_prompt(user_id: int, capabilities: tuple[AgentCapability, ...]) -> str:
    """总控模板 + 静态 JSON 契约；模板缺失时降级为内置角色提示词。"""
    try:
        rendered = prompt_template_service.get_rendered_prompt(
            PROMPT_AGENT, PROMPT_SCENE, user_id
        )
    except Exception:
        logger.warning("总控提示词读取失败，使用内置提示词", exc_info=True)
        rendered = DEFAULT_ROLE

    return (
        f"{rendered}\n\n"
        f"可用能力：\n{_format_capabilities(capabilities)}\n\n"
        f"{PLANNER_OUTPUT_RULES}"
    )


def _clean_text(value: Any, limit: int = MAX_TEXT_CHARS) -> str:
    """把任意值转成单行短文本，避免模型输出污染事件载荷。"""
    if value is None:
        return ""
    return " ".join(str(value).split())[:limit]


def _normalize_agents(raw: Any, allowed: set[str]) -> list[dict[str, Any]]:
    """只保留注册表内的能力名，去重并限制数量。"""
    if not isinstance(raw, list):
        return []
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name or name not in allowed or name in seen:
            continue
        slots = item.get("slots")
        result.append(
            {"name": name, "slots": slots if isinstance(slots, dict) else {}}
        )
        seen.add(name)
        if len(result) >= MAX_AGENTS:
            break
    return result


class FlowControllerAgent:
    """调用模型生成调度计划；任何失败都返回 None，让调用方走聊天。"""

    def plan(
        self,
        *,
        user_id: int,
        session_mode: int,
        request_text: str,
        capabilities: tuple[AgentCapability, ...],
        history: list[dict] | None = None,
        state: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """返回 {intent, confidence, reason, reply, agents}；不可用时返回 None。"""
        allowed = {capability.name for capability in capabilities} | {"chat_answer"}
        system_prompt = _build_system_prompt(user_id, capabilities)
        context = {
            "session_mode": session_mode,
            "request_text": request_text,
            "history": _format_history(history or []),
            "session_state": {
                "last_intent": (state or {}).get("last_intent"),
                "last_run_id": (state or {}).get("last_run_id"),
                "last_completed_run_id": (state or {}).get("last_completed_run_id"),
                "last_interview_id": (state or {}).get("last_interview_id"),
            },
        }
        prompt = ChatPromptTemplate.from_messages(
            [
                SystemMessage(content=system_prompt),
                ("human", "本轮调度上下文：\n{context}\n\n请输出调度 JSON。"),
            ]
        )

        try:
            raw = (
                (prompt | get_chat_model() | StrOutputParser()).invoke(
                    {"context": json.dumps(context, ensure_ascii=False)}
                )
                or ""
            )
            data = parse_json_object(raw)
        except Exception:
            logger.warning("总控规划失败，降级为聊天", exc_info=True)
            return None

        try:
            confidence = float(data.get("confidence") or 0)
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < MIN_CONFIDENCE:
            logger.info("总控规划置信度不足 | confidence=%s", confidence)
            return None

        agents = _normalize_agents(data.get("agents"), allowed)
        task_agents = [item for item in agents if item["name"] != "chat_answer"]
        if not task_agents:
            return None

        return {
            "intent": _clean_text(data.get("intent"), 64) or "chat",
            "confidence": confidence,
            "reason": _clean_text(data.get("reason")),
            "reply": _clean_text(data.get("reply")) or None,
            "agents": task_agents,
        }
