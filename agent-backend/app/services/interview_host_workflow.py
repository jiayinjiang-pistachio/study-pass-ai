"""业务层：面试主考官面试前准备工作流。

串联：校验面试会话 → 取最新简历 → 按 chunk_index 拼接正文 →
调用 InterviewHostAgent 提取变量 → 按「最新输入优先」覆盖 → 读取并注入提示词。
覆盖顺序：本轮明确表述 > 资料与简历中较新的一方（`updated_at` vs `create_time`）。
总控只负责分发，Agent 只负责模型提取，本层不实现模型调用细节。
"""

import logging
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
)
from . import prompt_injection_service, prompt_template_service

logger = logging.getLogger(__name__)

WORKFLOW_TYPE_INTERVIEW_PREPARE = "interview_prepare"
SESSION_MODE_INTERVIEW = 1
RESUME_DOC_CATEGORY = "resume"

PROMPT_AGENT = "interview_host"
PROMPT_SCENE = "interview"

DEFAULT_SCALAR = "未提供"
DEFAULT_LIST = "暂无"
# 可被用户输入覆盖的简历字段；优先级：本轮表述 > 资料 / 简历中较新的一方
OVERRIDE_FIELDS = ("target_job", "target_level", "target_skills", "weak_topics")

__all__ = ["WORKFLOW_TYPE_INTERVIEW_PREPARE", "start_interview_prepare"]


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
        "target_level=%s target_skills=%s weak_topics=%s stated_fields=%s",
        user_id,
        resource_id,
        result["target_job"],
        result["target_level"],
        result["target_skills"],
        result["weak_topics"],
        ",".join(stated) or "-",
    )
    return result, stated


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
    return overrides


def _profile_is_latest(profile: dict | None, resume: dict) -> bool:
    """资料最近写入时间不早于简历上传时间时，视为资料更新更晚。"""
    if not profile or not profile.get("updated_at"):
        return False
    create_time = resume.get("create_time")
    if create_time is None:
        return True
    return int(profile["updated_at"]) >= int(create_time.timestamp())


def _injection_values(variables: dict[str, Any]) -> dict[str, str]:
    """把最终变量转成模板注入值：数组用「、」连接，空数组回退默认文案。"""
    return {
        "target_job": variables["target_job"] or DEFAULT_SCALAR,
        "target_level": variables["target_level"] or DEFAULT_SCALAR,
        "target_skills": "、".join(variables["target_skills"]) or DEFAULT_LIST,
        "weak_topics": "、".join(variables["weak_topics"]) or DEFAULT_LIST,
    }


def start_interview_prepare(
    user_id: int, session_id: int, request_text: str = ""
) -> dict:
    """执行面试前准备：校验 → 取简历 → 提取变量 → 按最新输入覆盖 → 注入提示词。"""
    _get_interview_session(user_id, session_id)
    resume, resume_text = _load_resume(user_id)
    extracted, stated = _extract_variables(
        resume_text, request_text, user_id, resume["id"]
    )

    profile = user_profile_repo.get_by_user_id(user_id)
    profile_is_latest = _profile_is_latest(profile, resume)
    profile_overrides = _user_overrides(profile) if profile_is_latest else {}
    # 本轮明确表述优先级最高；opening_question 仍取简历提取结果
    stated_overrides = {
        field: stated[field] for field in OVERRIDE_FIELDS if field in stated
    }
    variables = {**extracted, **profile_overrides, **stated_overrides}
    if profile_overrides or stated_overrides:
        logger.info(
            "面试准备变量覆盖 | user_id=%s profile_newer=%s profile_fields=%s "
            "stated_fields=%s",
            user_id,
            profile_is_latest,
            ",".join(f for f in OVERRIDE_FIELDS if f in profile_overrides) or "-",
            ",".join(f for f in OVERRIDE_FIELDS if f in stated_overrides) or "-",
        )

    combined = prompt_template_service.get_combined_template(
        PROMPT_AGENT, PROMPT_SCENE, user_id
    )
    # 保留画像注入值（如 years_experience），再覆盖四个目标字段
    values = dict(combined.get("injected_variables") or {})
    values.update(_injection_values(variables))
    if "years_experience" in stated:
        # 用户本轮说的年限比资料更新，按同一套格式化规则覆盖
        values.update(
            prompt_injection_service.build_variables(
                {"years_experience": stated["years_experience"]},
                ["years_experience"],
            )
        )
    prompt = prompt_injection_service.render_template(
        combined["final_template"], values
    )

    logger.info(
        "面试主考官提示词生成完成 | user_id=%s session_id=%s prompt_chars=%s",
        user_id,
        session_id,
        len(prompt),
    )
    return {
        "session_id": session_id,
        "resume": {
            "resource_id": resume["id"],
            "file_name": resume["file_name"],
            "doc_category": resume["doc_category"],
            "create_time": resume["create_time"],
        },
        "variables": variables,
        "prompt": prompt,
        "opening_question": variables["opening_question"],
    }
