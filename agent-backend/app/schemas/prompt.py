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
    """生效提示词出参：公共 + 私有拼接结果，以及注入用户变量后的最终提示词。"""

    agent_name: str | None
    scene: str
    public_template: PromptTemplateOut | None
    private_template: PromptTemplateOut | None
    final_template: str
    variables: list[str]
    # 占位符替换后的提示词（未登录 / 无资料时按默认值渲染）
    rendered_template: str
    # 实际注入的变量（仅包含模板已声明且属于用户资料的白名单变量）
    injected_variables: dict[str, str]


class RollbackIn(BaseModel):
    """一键回滚入参。"""

    template_id: int = Field(..., gt=0, description="要恢复生效的模板版本 id")


class AgentConfigOut(BaseModel):
    """智能体配置出参。"""

    name: str
    display_name: str
    scenes: list[str]
    description: str
