"""业务层：面试主考官面试前准备（两阶段流程）。

第一阶段（本模块 `start_interview_prepare`）：
校验面试会话 → 取最新简历 → 按 chunk_index 拼接正文 → 调用 InterviewHostAgent
提取变量 → 按「最新输入优先」合并资料 / 简历 / 本轮表述 → 生成全字符串
`background` → 写入 `workflow_runs`（`status=pending_confirmation`）并返回待确认结果。

第二阶段（`interview_service.InterviewService.confirm`）：
用户编辑并确认 `background` 后，重新渲染主考官提示词，创建入口 ChatMessage 与
Interview，并把 run 置为 `confirmed`；同一 run_id 只允许确认一次。

覆盖顺序：本轮明确表述 > 资料与简历中较新的一方（`updated_at` vs `create_time`）。
总控只负责分发，Agent 只负责模型提取，本层不实现模型调用细节。
"""

import logging
import uuid
from typing import Any

from fastapi import status

from ..agent.agents.interview_host import InterviewHostAgent
from ..core.exceptions import BusinessException, SystemException
from ..core.retry import RetryExhaustedError
from ..db import (
    knowledge_chunk_repo,
    resource_repo,
    session_repo,
    user_profile_repo,
    workflow_run_repo,
)
from . import prompt_injection_service, prompt_template_service

logger = logging.getLogger(__name__)

WORKFLOW_TYPE_INTERVIEW_PREPARE = "interview_prepare"
SESSION_MODE_INTERVIEW = 1
RESUME_DOC_CATEGORY = "resume"

# 工作流状态：第一阶段等待确认，第二阶段确认中 / 已确认 / 失败
STATUS_PENDING_CONFIRMATION = "pending_confirmation"
STATUS_CONFIRMING = "confirming"
STATUS_CONFIRMED = "confirmed"
STATUS_FAILED = "failed"

PROMPT_AGENT = "interview_host"
PROMPT_SCENE = "interview"

NOT_PROVIDED = "未提供"
DEFAULT_SCALAR = "未提供"
DEFAULT_LIST = "暂无"

# 可被资料 / 本轮表述覆盖的简历字段；优先级：本轮表述 > 资料 / 简历中较新的一方
OVERRIDE_FIELDS = ("target_job", "target_level", "target_skills", "weak_topics")
YEARS_FIELD = "years_experience"
YEARS_MIN = 0
YEARS_MAX = 60

# 背景字段顺序固定，前后端按同一契约展示
BACKGROUND_FIELDS = (
    "target_job",
    "target_level",
    "years_experience",
    "target_skills",
    "project_experience",
    "weak_topics",
    "opening_question",
)

__all__ = [
    "BACKGROUND_FIELDS",
    "STATUS_CONFIRMED",
    "STATUS_CONFIRMING",
    "STATUS_FAILED",
    "STATUS_PENDING_CONFIRMATION",
    "WORKFLOW_TYPE_INTERVIEW_PREPARE",
    "build_interview_prompt",
    "start_interview_prepare",
]


def _get_interview_session(user_id: int, session_id: int) -> dict:
    """会话必须属于当前用户且为面试模式。"""
    session = session_repo.get_for_user(session_id, user_id)
    if session is None:
        raise BusinessException(
            "会话不存在",
            http_status=status.HTTP_404_NOT_FOUND,
            detail=f"session_id={session_id} user_id={user_id}",
        )
    if session["session_mode"] != SESSION_MODE_INTERVIEW:
        raise BusinessException(
            "当前会话不是面试会话",
            http_status=status.HTTP_400_BAD_REQUEST,
            detail=f"session_id={session_id} session_mode={session['session_mode']}",
        )
    return session


def _load_resume(user_id: int) -> tuple[dict, str]:
    """取最新简历资源并拼接切片正文；资源或解析结果缺失时提前失败。"""
    resume = resource_repo.get_latest_by_category(user_id, RESUME_DOC_CATEGORY)
    if resume is None:
        raise BusinessException(
            "未找到简历，请先上传简历",
            http_status=status.HTTP_404_NOT_FOUND,
            detail=f"user_id={user_id} doc_category={RESUME_DOC_CATEGORY}",
        )

    resume_text = knowledge_chunk_repo.get_text_by_resource(resume["id"])
    if not resume_text.strip():
        raise BusinessException(
            "简历内容尚未解析完成，请稍后重试",
            http_status=status.HTTP_409_CONFLICT,
            detail=f"resource_id={resume['id']}",
        )
    return resume, resume_text


def _extract_variables(
    resume_text: str, request_text: str, user_id: int, resource_id: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    """调用 Agent 提取简历变量与用户本轮表述；配置缺失转 503，模型失败转 502。"""
    try:
        result = InterviewHostAgent().extract_variables(resume_text, request_text)
    except RetryExhaustedError as exc:
        cause = exc.last_error
        if isinstance(cause, RuntimeError):
            raise SystemException(
                "面试主考官服务暂不可用",
                http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(cause),
            ) from exc
        logger.error(
            "面试准备变量提取失败 | user_id=%s resource_id=%s",
            user_id,
            resource_id,
            exc_info=True,
        )
        raise SystemException(
            "面试准备失败，请稍后重试",
            http_status=status.HTTP_502_BAD_GATEWAY,
            detail=f"resource_id={resource_id} error={exc}",
        ) from exc

    stated = result.pop("user_stated", {})
    logger.info(
        "面试主考官变量提取完成 | user_id=%s resource_id=%s target_job=%s "
        "target_level=%s years_experience=%s target_skills=%s weak_topics=%s "
        "stated_fields=%s",
        user_id,
        resource_id,
        result["target_job"],
        result["target_level"],
        result.get("years_experience"),
        result["target_skills"],
        result["weak_topics"],
        ",".join(stated) or "-",
    )
    return result, stated


def _year_value(value: object) -> int | None:
    """把年限清洗为 0..60 的整数；缺失或非法返回 None。"""
    if value is None or str(value).strip() == "":
        return None
    try:
        years = int(value)
    except (TypeError, ValueError):
        return None
    return years if YEARS_MIN <= years <= YEARS_MAX else None


def _user_overrides(profile: dict | None) -> dict[str, Any]:
    """取用户资料中真实填写的字段；未填写 / 空值不参与覆盖，交给简历兜底。"""
    if not profile:
        return {}
    overrides: dict[str, Any] = {}
    job = prompt_injection_service.sanitize_text(profile.get("target_job"))
    if job:
        overrides["target_job"] = job
    level = prompt_injection_service.sanitize_text(profile.get("target_level"))
    if level:
        overrides["target_level"] = level
    skills = prompt_injection_service.sanitize_items(profile.get("target_skills"))
    if skills:
        overrides["target_skills"] = skills
    weak_topics = prompt_injection_service.sanitize_items(profile.get("weak_topics"))
    if weak_topics:
        overrides["weak_topics"] = weak_topics
    years = _year_value(profile.get(YEARS_FIELD))
    if years is not None:
        overrides[YEARS_FIELD] = years
    return overrides


def _profile_is_latest(profile: dict | None, resume: dict) -> bool:
    """资料最近写入时间不早于简历上传时间时，视为资料更新更晚。"""
    if not profile or not profile.get("updated_at"):
        return False
    create_time = resume.get("create_time")
    if create_time is None:
        return True
    return int(profile["updated_at"]) >= int(create_time.timestamp())


def _editable_text(value: object, max_chars: int = 100) -> str:
    """把提取值转成前端可编辑文本：空值 / 「未提供」统一为空字符串。"""
    text = prompt_injection_service.sanitize_text(value, max_chars)
    return "" if text == NOT_PROVIDED else text


def _format_years(value: object) -> str:
    """背景中的年限：0 → 应届/无经验，N → N 年，缺失 → 空字符串。"""
    years = _year_value(value)
    if years is None:
        return ""
    if years <= 0:
        return "应届/无经验"
    return f"{years} 年"


def _build_background(variables: dict[str, Any]) -> dict[str, str]:
    """把合并后的变量转成全字符串 background（技能 / 薄弱点用「、」连接）。"""
    return {
        "target_job": _editable_text(variables.get("target_job")),
        "target_level": _editable_text(variables.get("target_level")),
        "years_experience": _format_years(variables.get(YEARS_FIELD)),
        "target_skills": "、".join(
            prompt_injection_service.sanitize_items(variables.get("target_skills"))
        ),
        "project_experience": _editable_text(
            variables.get("project_experience"), 1000
        ),
        "weak_topics": "、".join(
            prompt_injection_service.sanitize_items(variables.get("weak_topics"))
        ),
        "opening_question": _editable_text(
            variables.get("opening_question"), 500
        ),
    }


def build_interview_prompt(background: dict[str, str], user_id: int) -> str:
    """按用户确认后的 background 重新渲染主考官提示词。

    背景已是字符串（技能 / 薄弱点用「、」连接），直接作为模板变量注入；
    空值回退为「未提供 / 暂无」，避免提示词出现空白占位。
    """
    combined = prompt_template_service.get_combined_template(
        PROMPT_AGENT, PROMPT_SCENE, user_id
    )
    values = dict(combined.get("injected_variables") or {})
    values.update(
        {
            "target_job": prompt_injection_service.sanitize_text(
                background.get("target_job")
            )
            or DEFAULT_SCALAR,
            "target_level": prompt_injection_service.sanitize_text(
                background.get("target_level")
            )
            or DEFAULT_SCALAR,
            "years_experience": prompt_injection_service.sanitize_text(
                background.get("years_experience"), 32
            )
            or DEFAULT_SCALAR,
            "target_skills": prompt_injection_service.sanitize_text(
                background.get("target_skills"), 1000
            )
            or DEFAULT_LIST,
            "weak_topics": prompt_injection_service.sanitize_text(
                background.get("weak_topics"), 1000
            )
            or DEFAULT_LIST,
        }
    )
    return prompt_injection_service.render_template(combined["final_template"], values)


def start_interview_prepare(
    user_id: int, session_id: int, request_text: str = ""
) -> dict:
    """第一阶段：校验 → 取简历 → 提取变量 → 合并 → 生成待确认背景并落库。"""
    _get_interview_session(user_id, session_id)
    resume, resume_text = _load_resume(user_id)
    extracted, stated = _extract_variables(
        resume_text, request_text, user_id, resume["id"]
    )

    profile = user_profile_repo.get_by_user_id(user_id)
    profile_is_latest = _profile_is_latest(profile, resume)
    profile_overrides = _user_overrides(profile) if profile_is_latest else {}
    # 本轮明确表述优先级最高；opening_question / project_experience 仍取简历
    stated_overrides = {
        field: stated[field]
        for field in (*OVERRIDE_FIELDS, YEARS_FIELD)
        if field in stated
    }
    variables = {**extracted, **profile_overrides, **stated_overrides}
    if profile_overrides or stated_overrides:
        logger.info(
            "面试准备变量覆盖 | user_id=%s profile_newer=%s profile_fields=%s "
            "stated_fields=%s",
            user_id,
            profile_is_latest,
            ",".join(
                f for f in (*OVERRIDE_FIELDS, YEARS_FIELD) if f in profile_overrides
            )
            or "-",
            ",".join(
                f for f in (*OVERRIDE_FIELDS, YEARS_FIELD) if f in stated_overrides
            )
            or "-",
        )

    background = _build_background(variables)
    resume_info = {
        "resource_id": resume["id"],
        "file_name": resume["file_name"],
        "doc_category": resume["doc_category"],
        "create_time": resume["create_time"],
    }
    run_id = str(uuid.uuid4())
    state = {
        "run_id": run_id,
        "user_id": user_id,
        "session_id": session_id,
        "request_text": request_text,
        "status": STATUS_PENDING_CONFIRMATION,
        "background": background,
        "source_variables": variables,
    }
    workflow_run_repo.insert(
        {
            "run_id": run_id,
            "user_id": user_id,
            "session_id": session_id,
            "workflow_type": WORKFLOW_TYPE_INTERVIEW_PREPARE,
            "status": STATUS_PENDING_CONFIRMATION,
            "state_json": state,
        }
    )

    logger.info(
        "面试背景待确认 | user_id=%s session_id=%s run_id=%s",
        user_id,
        session_id,
        run_id,
    )
    return {
        "session_id": session_id,
        "run_id": run_id,
        "status": STATUS_PENDING_CONFIRMATION,
        "resume": resume_info,
        "background": background,
    }
