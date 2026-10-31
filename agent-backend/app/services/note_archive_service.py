"""业务层：note_archiver 笔记归档智能体。

学习测评完成后由 A2A 派发触发：
1. 注入模板变量后调用模型，只生成 Markdown 正文（不要求 JSON）；
2. 从 Markdown 提取标题，补齐 tags 与 metadata；
3. 正文残留未替换占位符时拒绝归档，避免把残缺笔记落库。

本服务只负责生成与整理；落库由 NoteService 完成，失败只影响派发结果，
不会回滚测评已完成的业务状态。
"""

import json
import logging
import re
import time
from typing import Any

from fastapi import status
from langchain_core.messages import SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from ..agent.a2a import A2AEnvelope
from ..core.exceptions import BusinessException, SystemException
from ..core.retry import run_with_retry
from ..db import user_profile_repo, workflow_run_repo
from . import prompt_injection_service, prompt_template_service
from .a2a_handoff_service import register_handler
from .ai.llm import get_chat_model
from .note_service import NoteService

logger = logging.getLogger(__name__)

AGENT_NAME = "note_archiver"
PROMPT_AGENT = "note_archiver"
PROMPT_SCENE = "note"
NOTE_TAG = "学习测评"
TITLE_MAX_CHARS = 60
WORKFLOW_TYPE = "learning_quiz"

SECTION_TITLES = frozenset({"测评概览", "薄弱点总结", "错题复盘", "复习建议"})
# 与 prompt_injection_service 的占位符语法保持一致，仅用于检测正文残留
_LEFTOVER_PLACEHOLDER = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")
_HEADING_PATTERN = re.compile(r"^#{1,6}\s+(.+)$")
_TITLE_LABEL_PATTERN = re.compile(r"^标题\s*[:：]\s*(.+)$")

DEFAULT_NOTE_ROLE = """你是笔记归档助手。请根据本次学习测评结果，整理一份可直接复习的 Markdown 笔记。"""

NOTE_OUTPUT_RULES = """输出要求（优先于上方模板中的冲突规则）：
1. 只输出 Markdown 正文，不要 JSON、代码块包裹或额外解释；
2. 第一行用一级标题给出笔记标题；
3. 正文必须包含四个二级标题：## 测评概览、## 薄弱点总结、## 错题复盘、## 复习建议；
4. 不要编造测评中没有的信息；不确定的内容标记「待确认」。"""


def _clean_text(value: Any, limit: int | None = None) -> str:
    """把任意值转成单行文本；空白值返回空串。"""
    if value is None:
        return ""
    text = " ".join(str(value).split())
    return text[:limit] if limit else text


def _string_list(value: Any) -> list[str]:
    """只保留非空字符串项，避免 state 中的脏数据污染笔记。"""
    if not isinstance(value, (list, tuple)):
        return []
    return [text for item in value if (text := _clean_text(item))]


def _sorted_unique(items: list[str]) -> list[str]:
    """去重并保持首次出现顺序，保证同一份 state 生成稳定标签。"""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _strip_code_fence(text: str) -> str:
    """模型偶尔会把 Markdown 包进代码块，去掉外层围栏后只保留正文。"""
    text = text.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _extract_title(content: str, fallback: str) -> str:
    """从 Markdown 标题提取笔记标题；跳过四个固定章节标题。"""
    for line in content.splitlines():
        text = line.strip()
        if not text:
            continue
        heading = _HEADING_PATTERN.match(text)
        if heading:
            title = _clean_text(heading.group(1), TITLE_MAX_CHARS)
            if title and title not in SECTION_TITLES:
                return title
            continue
        label = _TITLE_LABEL_PATTERN.match(text)
        if label:
            return _clean_text(label.group(1), TITLE_MAX_CHARS) or fallback
    return fallback


def _prompt_variables(
    state: dict[str, Any],
    weaknesses: list[str],
    question_count: int,
    correct_count: int,
    wrong_count: int,
) -> dict[str, str]:
    """业务变量：覆盖模板未声明的测评上下文；值已清洗，不会二次解析。"""
    return {
        "weak_topics": "、".join(prompt_injection_service.sanitize_items(weaknesses))
        or "暂无",
        "question_count": str(question_count),
        "score": str(state.get("score", 0)),
        "correct_count": str(correct_count),
        "wrong_count": str(wrong_count),
    }


def _build_system_prompt(user_id: int, variables: dict[str, str]) -> str:
    """公共 + 私有模板 + 用户画像 + 本次测评变量；模板不可用时降级为内置角色。"""
    try:
        combined = prompt_template_service.get_combined_template(
            PROMPT_AGENT, PROMPT_SCENE, user_id
        )
        profile = (
            user_profile_repo.get_by_user_id(user_id)
            if user_id is not None
            else None
        )
        injected = prompt_injection_service.build_variables(
            profile, combined["variables"]
        )
        injected.update(variables)
        rendered = prompt_injection_service.render_template(
            combined["final_template"], injected
        )
    except Exception:
        logger.warning(
            "笔记提示词读取失败，使用内置提示词 | agent=%s scene=%s",
            PROMPT_AGENT,
            PROMPT_SCENE,
            exc_info=True,
        )
        rendered = DEFAULT_NOTE_ROLE
    return f"{rendered}\n\n{NOTE_OUTPUT_RULES}"


def _generate_markdown(
    user_id: int, state: dict[str, Any], variables: dict[str, str]
) -> str:
    """调用模型生成 Markdown 正文；瞬时故障走统一重试。"""
    prompt = ChatPromptTemplate.from_messages(
        [
            SystemMessage(content=_build_system_prompt(user_id, variables)),
            ("human", "以下是本次学习测评的完整结果，请生成 Markdown 笔记：\n{payload}"),
        ]
    )
    payload = json.dumps(
        {
            "request_text": _clean_text(state.get("request_text")),
            "score": state.get("score", 0),
            "weaknesses": _string_list(state.get("weaknesses")),
            "review": state.get("review"),
            "quiz": state.get("quiz") or [],
            "answers": state.get("answers") or [],
            "evaluation": state.get("evaluation") or [],
        },
        ensure_ascii=False,
    )
    raw = run_with_retry(
        lambda: (prompt | get_chat_model() | StrOutputParser()).invoke(
            {"payload": payload}
        )
        or "",
        node=AGENT_NAME,
    )
    return _strip_code_fence(raw)


class NoteArchiveService:
    """把测评结果转换成笔记结构；模型只产出 Markdown，结构由本服务补齐。"""

    def archive_from_state(
        self, user_id: int, state: dict[str, Any] | None
    ) -> dict[str, Any]:
        """直接基于工作流 state 生成笔记，适合派发时已有完整快照的场景。"""
        if not isinstance(state, dict) or not state:
            raise BusinessException(
                "测评状态为空，无法生成笔记",
                http_status=status.HTTP_400_BAD_REQUEST,
                detail=f"user_id={user_id}",
            )

        quiz = [item for item in state.get("quiz") or [] if isinstance(item, dict)]
        evaluations = [
            item for item in state.get("evaluation") or [] if isinstance(item, dict)
        ]
        weaknesses = _string_list(state.get("weaknesses"))
        correct_count = sum(
            1 for item in evaluations if item.get("correct") is True
        )
        wrong_count = max(0, len(quiz) - correct_count)

        content = _generate_markdown(
            user_id,
            state,
            _prompt_variables(
                state, weaknesses, len(quiz), correct_count, wrong_count
            ),
        )
        if not content:
            raise SystemException(
                "笔记生成失败：模型返回空内容",
                http_status=status.HTTP_502_BAD_GATEWAY,
                detail=f"run_id={state.get('run_id')}",
            )

        leftovers = sorted(set(_LEFTOVER_PLACEHOLDER.findall(content)))
        if leftovers:
            raise SystemException(
                "笔记正文存在未替换的模板占位符，已取消保存",
                http_status=status.HTTP_502_BAD_GATEWAY,
                detail=f"run_id={state.get('run_id')} placeholders={leftovers}",
            )

        request_text = _clean_text(state.get("request_text"), TITLE_MAX_CHARS)
        fallback_title = (
            f"学习测评笔记：{request_text}" if request_text else "学习测评笔记"
        )
        title = _extract_title(content, fallback_title)

        return {
            "title": title,
            "content": content,
            "tags": _sorted_unique([NOTE_TAG, *weaknesses]),
            "metadata": {
                "run_id": state.get("run_id"),
                "user_id": user_id,
                "session_id": state.get("session_id"),
                "workflow_type": WORKFLOW_TYPE,
                "score": state.get("score", 0),
                "question_count": len(quiz),
                "correct_count": correct_count,
                "wrong_count": wrong_count,
                "weakness_count": len(weaknesses),
                "generated_at": int(time.time()),
            },
        }

    def archive_from_run(self, user_id: int, run_id: str) -> dict[str, Any]:
        """按 run_id 读取 workflow_runs.state_json 后生成笔记，按用户隔离。"""
        row = workflow_run_repo.get_for_user(run_id, user_id)
        if row is None:
            raise BusinessException(
                "测评不存在",
                http_status=status.HTTP_404_NOT_FOUND,
                detail=f"run_id={run_id} user_id={user_id}",
            )
        return self.archive_from_state(user_id, row.get("state_json") or {})


def archive_note_handler(
    _: A2AEnvelope, context: dict[str, Any]
) -> dict[str, Any]:
    """A2A handler：只做编排，先生成笔记再交给 NoteService 保存。"""
    user_id = context.get("user_id")
    if not isinstance(user_id, int):
        raise RuntimeError("缺少 user_id，无法归档笔记")

    state = context.get("state")
    run_id = context.get("run_id")
    if isinstance(state, dict) and state:
        archive = NoteArchiveService().archive_from_state(user_id, state)
        session_id = context.get("session_id") or state.get("session_id")
        run_id = run_id or state.get("run_id")
    else:
        if not run_id:
            raise RuntimeError("缺少 state 或 run_id，无法归档笔记")
        archive = NoteArchiveService().archive_from_run(user_id, str(run_id))
        session_id = context.get("session_id")

    if not isinstance(session_id, int) or not run_id:
        raise RuntimeError("缺少 session_id 或 run_id，无法保存笔记")
    return NoteService().save_learning_quiz_note(
        user_id, session_id, str(run_id), archive
    )


# 导入本模块即完成注册；新增下游智能体按同样方式登记 handler 即可
register_handler(AGENT_NAME, archive_note_handler)
