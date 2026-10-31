"""校验层：面试主考官面试前准备的出参模型。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ResumeInfoOut(BaseModel):
    """本次准备使用的简历资源信息。"""

    resource_id: int = Field(..., description="resources 表主键")
    file_name: str = Field(..., description="简历文件名")
    doc_category: str | None = Field(None, description="文档业务类型，固定为 resume")
    create_time: datetime | None = Field(None, description="上传时间")


class InterviewVariablesOut(BaseModel):
    """从简历提取的面试准备变量。"""

    target_job: str = Field(..., description="目标岗位")
    target_level: str = Field(..., description="目标职级 / 经验层级")
    target_skills: list[str] = Field(default_factory=list, description="已掌握技能")
    weak_topics: list[str] = Field(default_factory=list, description="薄弱点")
    opening_question: str = Field(..., description="面试开场问题")


class InterviewPrepareOut(BaseModel):
    """面试前准备工作流出参。"""

    route: Literal["workflow"] = Field("workflow", description="固定为 workflow")
    agent_name: str = Field(..., description="固定为 interview_host")
    workflow_type: Literal["interview_prepare"] = Field(
        "interview_prepare", description="工作流类型"
    )
    session_id: int = Field(..., description="面试会话 ID")
    resume: ResumeInfoOut = Field(..., description="使用的简历资源")
    variables: InterviewVariablesOut = Field(..., description="提取出的变量")
    prompt: str = Field(..., description="注入变量后的面试主考官提示词")
    opening_question: str = Field(..., description="面试开场问题")
