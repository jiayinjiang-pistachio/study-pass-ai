"""校验层：难点讲解知识卡工作流出参模型。"""

from typing import Literal

from pydantic import BaseModel, Field


class DifficultyCardOut(BaseModel):
    """知识卡生成结果：只返回卡片基础信息，完整内容用于会话回显。"""

    route: Literal["workflow"] = Field("workflow", description="固定为 workflow")
    agent_name: str = Field(..., description="固定为 difficulty_learner")
    workflow_type: Literal["difficulty_card"] = Field(
        "difficulty_card", description="工作流类型"
    )
    session_id: int = Field(..., description="所属会话 ID")
    run_id: str = Field(..., description="本次知识卡运行 ID")
    status: Literal["completed"] = Field("completed", description="固定为 completed")
    title: str = Field(..., description="知识卡标题")
    resource_id: int = Field(..., description="图片资源 ID（resources 表主键）")
    image_url: str = Field(
        ..., description="图片预签名地址；签名失败时为空串，可读历史消息时重新续签"
    )
