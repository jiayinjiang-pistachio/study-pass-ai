"""校验层：面试主考官面试前准备（两阶段）出参 / 背景模型。"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

# 背景字段统一为字符串，前端用单行文本框编辑；长度上限与提取清洗保持一致
EditableText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]


class ResumeInfoOut(BaseModel):
    """本次准备使用的简历资源信息。"""

    resource_id: int = Field(..., description="resources 表主键")
    file_name: str = Field(..., description="简历文件名")
    doc_category: str | None = Field(None, description="文档业务类型，固定为 resume")
    create_time: datetime | None = Field(None, description="上传时间")


class InterviewBackground(BaseModel):
    """待确认 / 已确认的面试背景，全部为可编辑字符串。"""

    target_job: ShortText = Field("", description="目标岗位")
    target_level: ShortText = Field("", description="目标职级 / 经验层级")
    years_experience: ShortText = Field("", description="工作年限，如「5 年」")
    target_skills: EditableText = Field("", description="已掌握技能，用「、」分隔")
    project_experience: EditableText = Field("", description="代表性项目经历")
    weak_topics: EditableText = Field("", description="薄弱点，用「、」分隔")
    opening_question: EditableText = Field("", description="面试开场问题")


class InterviewPrepareOut(BaseModel):
    """第一阶段出参：只返回待确认背景，不返回最终提示词。"""

    route: Literal["workflow"] = Field("workflow", description="固定为 workflow")
    agent_name: str = Field(..., description="固定为 interview_host")
    workflow_type: Literal["interview_prepare"] = Field(
        "interview_prepare", description="工作流类型"
    )
    session_id: int = Field(..., description="面试会话 ID")
    run_id: str = Field(..., description="本次面试准备运行 ID，确认时回传")
    status: Literal["pending_confirmation"] = Field(
        "pending_confirmation", description="固定为 pending_confirmation"
    )
    resume: ResumeInfoOut = Field(..., description="使用的简历资源")
    background: InterviewBackground = Field(..., description="待确认的面试背景")
