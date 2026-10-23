"""校验层：提示词版本管理的出参模型。"""

from pydantic import BaseModel, Field


class PromptTemplateOut(BaseModel):
    """提示词版本出参。"""

    id: int
    agent_name: str | None
    scene: str
    template_type: int
    template_content: str
    variables: list[str]
    version: int
    is_active: int
    description: str | None
    created_at: int


class ActivePromptOut(BaseModel):
    """生效提示词出参：公共模板 + 私有模板及其拼接结果。"""

    agent_name: str | None
    scene: str
    public_template: PromptTemplateOut | None
    private_template: PromptTemplateOut | None
    final_template: str
    variables: list[str]


class RollbackIn(BaseModel):
    """一键回滚入参。"""

    template_id: int = Field(..., gt=0, description="要恢复生效的模板版本 id")


class AgentConfigOut(BaseModel):
    """智能体配置出参。"""

    name: str
    display_name: str
    scenes: list[str]
    description: str
