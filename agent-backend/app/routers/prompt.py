"""路由层：提示词版本管理接口。

统一前缀 /api/prompt，整组需登录。
"""

from fastapi import APIRouter, Depends, Query

from ..schemas.prompt import (
    ActivePromptOut,
    AgentConfigOut,
    PromptTemplateOut,
    RollbackIn,
)
from ..schemas.response import ResponseModel, ok
from ..services import prompt_template_service
from .deps import get_current_user

router = APIRouter(
    prefix="/api/prompt",
    tags=["prompt"],
    dependencies=[Depends(get_current_user)],
)


@router.get(
    "/templates/{agent_name}/{scene}",
    response_model=ResponseModel[PromptTemplateOut],
    summary="获取指定作用域的生效模板",
)
def get_active_template(agent_name: str, scene: str) -> dict:
    """只返回该作用域自身的生效版本，不做公共 / 私有拼接。

    `common/common` 返回公共通用模板；完整提示词请用 `/full-prompt`。
    """
    return ok(prompt_template_service.get_active_template(agent_name, scene))


@router.get(
    "/full-prompt",
    response_model=ResponseModel[ActivePromptOut],
    summary="获取完整提示词（公共 + 私有拼接）",
)
def get_full_prompt(
    agent_name: str = Query(..., description="智能体名"),
    scene: str = Query(..., description="使用场景"),
) -> dict:
    """返回公共模板、私有模板与拼接后的最终提示词。"""
    return ok(prompt_template_service.get_combined_template(agent_name, scene))


@router.post(
    "/rollback",
    response_model=ResponseModel[PromptTemplateOut],
    summary="一键回滚到指定模板版本",
)
def rollback_template(payload: RollbackIn) -> dict:
    """把指定历史版本重新置为生效，同作用域其他版本自动下线。"""
    return ok(prompt_template_service.rollback(payload.template_id))


@router.get(
    "/config/agents",
    response_model=ResponseModel[list[AgentConfigOut]],
    summary="查询智能体配置",
)
def list_agents() -> dict:
    """返回 7 个智能体的名称、展示名、支持场景与职责说明。"""
    return ok(prompt_template_service.list_agents())
