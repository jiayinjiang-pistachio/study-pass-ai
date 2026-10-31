"""业务层：面试主考官面试前准备工作流。

串联：校验面试会话 → 取最新简历 → 按 chunk_index 拼接正文 →
调用 InterviewHostAgent 提取变量 → 读取并注入 interview_host 提示词。
总控只负责分发，Agent 只负责模型提取，本层不实现模型调用细节。
"""

import logging
from typing import Any

from fastapi import status

from ..agent.agents.interview_host import InterviewHostAgent
from ..core.exceptions import BusinessException, SystemException
from ..core.retry import RetryExhaustedError
from ..db import knowledge_chunk_repo, resource_repo, session_repo
from . import prompt_injection_service, prompt_template_service

logger = logging.getLogger(__name__)

WORKFLOW_TYPE_INTERVIEW_PREPARE = "interview_prepare"
SESSION_MODE_INTERVIEW = 1
RESUME_DOC_CATEGORY = "resume"

PROMPT_AGENT = "interview_host"
PROMPT_SCENE = "interview"

DEFAULT_SCALAR = "未提供"
DEFAULT_LIST = "暂无"

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


def _extract_variables(resume_text: str, user_id: int, resource_id: int) -> dict:
    """调用 Agent 提取变量；配置缺失转 503，模型 / 解析失败转 502。"""
    try:
        variables = InterviewHostAgent().extract_variables(resume_text)
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

    logger.info(
        "面试主考官变量提取完成 | user_id=%s resource_id=%s target_job=%s "
        "target_level=%s target_skills=%s weak_topics=%s",
        user_id,
        resource_id,
        variables["target_job"],
        variables["target_level"],
        variables["target_skills"],
        variables["weak_topics"],
    )
    return variables


def _injection_values(variables: dict[str, Any]) -> dict[str, str]:
    """把提取结果转成模板注入值：数组用「、」连接，空数组回退默认文案。"""
    return {
        "target_job": variables["target_job"] or DEFAULT_SCALAR,
        "target_level": variables["target_level"] or DEFAULT_SCALAR,
        "target_skills": "、".join(variables["target_skills"]) or DEFAULT_LIST,
        "weak_topics": "、".join(variables["weak_topics"]) or DEFAULT_LIST,
    }


def start_interview_prepare(user_id: int, session_id: int) -> dict:
    """执行面试前准备：校验 → 取简历 → 提取变量 → 注入提示词 → 返回结果。"""
    _get_interview_session(user_id, session_id)
    resume, resume_text = _load_resume(user_id)
    variables = _extract_variables(resume_text, user_id, resume["id"])

    combined = prompt_template_service.get_combined_template(
        PROMPT_AGENT, PROMPT_SCENE, user_id
    )
    # 先保留用户画像注入值（如 years_experience），再用简历提取值覆盖画像字段
    values = dict(combined.get("injected_variables") or {})
    values.update(_injection_values(variables))
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
