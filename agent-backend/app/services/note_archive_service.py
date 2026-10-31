"""业务层：note_archiver 笔记归档智能体。

学习测评完成后由 A2A 派发触发：把完整工作流 state 转成可保存、可渲染、可检索的
笔记 JSON。笔记生成沿用纯函数式转换，不调用模型；失败只体现在派发结果里，
不会回滚测评已完成的业务状态。
"""

import time
from typing import Any

from fastapi import status

from ..agent.a2a import A2AEnvelope
from ..core.exceptions import BusinessException
from ..db import workflow_run_repo
from .a2a_handoff_service import register_handler

AGENT_NAME = "note_archiver"
NOTE_TAG = "学习测评"
TITLE_MAX_CHARS = 60
WORKFLOW_TYPE = "learning_quiz"


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


def _format_answer(question: dict, value: Any) -> str:
    """把作答值渲染成「选项标识. 选项内容」；简答题原样返回。"""
    options = {
        option.get("key"): _clean_text(option.get("text"))
        for option in question.get("options") or []
        if isinstance(option, dict) and option.get("key")
    }

    def _one(key: str) -> str:
        text = options.get(key)
        return f"{key}. {text}" if text else key

    if isinstance(value, list):
        rendered = [_one(_clean_text(item)) for item in value if _clean_text(item)]
        return "、".join(rendered) or "未作答"
    text = _clean_text(value)
    return _one(text) if text else "未作答"


def _sorted_unique(items: list[str]) -> list[str]:
    """去重并保持首次出现顺序，保证同一份 state 生成稳定笔记。"""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _build_content(state: dict[str, Any]) -> tuple[str, int, int]:
    """生成 Markdown 正文，返回 (content, 答对题数, 错题数)。"""
    quiz = [item for item in state.get("quiz") or [] if isinstance(item, dict)]
    evaluations = {
        item.get("question_id"): item
        for item in state.get("evaluation") or []
        if isinstance(item, dict)
    }
    answers = {
        item.get("question_id"): item.get("value")
        for item in state.get("answers") or []
        if isinstance(item, dict)
    }
    weaknesses = _string_list(state.get("weaknesses"))
    raw_review = state.get("review")
    # 整体建议保留原始换行，直接作为 Markdown 段落渲染
    review = (raw_review.strip() if isinstance(raw_review, str) else "") or "暂无整体建议。"

    correct_count = sum(
        1 for item in evaluations.values() if item.get("correct") is True
    )
    wrong_questions = [
        question
        for question in quiz
        if evaluations.get(question.get("question_id"), {}).get("correct") is not True
    ]

    score = state.get("score", 0)
    request_text = _clean_text(state.get("request_text"), TITLE_MAX_CHARS) or "学习测评"

    lines = [
        "## 测评概览",
        "",
        f"- 测评需求：{request_text}",
        f"- 得分：{score} 分",
        f"- 题目：{len(quiz)} 题，答对 {correct_count} 题，答错 {len(wrong_questions)} 题",
        "",
        "## 薄弱点总结",
        "",
    ]
    if weaknesses:
        lines.extend(f"- {item}" for item in weaknesses)
    else:
        lines.append("本次测评未发现明显薄弱点。")

    lines.extend(["", "## 错题复盘", ""])
    if wrong_questions:
        for question in wrong_questions:
            question_id = question.get("question_id")
            stem = _clean_text(question.get("stem")) or f"第 {question_id} 题"
            comment = (
                _clean_text(evaluations.get(question_id, {}).get("comment"))
                or "暂无点评。"
            )
            answer = _format_answer(question, answers.get(question_id))
            lines.extend(
                [
                    f"### 第 {question_id} 题：{stem}",
                    "",
                    f"- 你的作答：{answer}",
                    f"- 点评：{comment}",
                    "",
                ]
            )
    else:
        lines.extend(["本次测评没有错题，继续保持。", ""])

    lines.extend(["## 复习建议", "", review])
    return "\n".join(lines).strip(), correct_count, len(wrong_questions)


class NoteArchiveService:
    """把测评结果转换成笔记 JSON；不负责持久化，调用方可直接保存或渲染。"""

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

        weaknesses = _string_list(state.get("weaknesses"))
        content, correct_count, wrong_count = _build_content(state)
        question_count = len(
            [item for item in state.get("quiz") or [] if isinstance(item, dict)]
        )
        request_text = _clean_text(state.get("request_text"), TITLE_MAX_CHARS)
        title = (
            f"学习测评笔记：{request_text}" if request_text else "学习测评笔记"
        )

        return {
            "weaknesses": weaknesses,
            "a2a_envelope": state.get("a2a_envelope"),
            "title": title,
            "content": content,
            "tags": _sorted_unique([NOTE_TAG, *weaknesses]),
            "metadata": {
                "run_id": state.get("run_id"),
                "user_id": user_id,
                "session_id": state.get("session_id"),
                "workflow_type": WORKFLOW_TYPE,
                "score": state.get("score", 0),
                "question_count": question_count,
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
    _envelope: A2AEnvelope, context: dict[str, Any]
) -> dict[str, Any]:
    """A2A handler：优先使用派发上下文里的完整 state，否则回源运行记录。"""
    user_id = context.get("user_id")
    if not isinstance(user_id, int):
        raise RuntimeError("缺少 user_id，无法归档笔记")

    state = context.get("state")
    if isinstance(state, dict) and state:
        return NoteArchiveService().archive_from_state(user_id, state)

    run_id = context.get("run_id")
    if not run_id:
        raise RuntimeError("缺少 state 或 run_id，无法归档笔记")
    return NoteArchiveService().archive_from_run(user_id, str(run_id))


# 导入本模块即完成注册；新增下游智能体按同样方式登记 handler 即可
register_handler(AGENT_NAME, archive_note_handler)
