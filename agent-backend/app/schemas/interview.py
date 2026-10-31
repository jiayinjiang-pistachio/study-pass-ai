"""校验层：面试确认入参、面试详情与确认出参模型。"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints

from .interview_host import InterviewBackground


class InterviewConfirmIn(BaseModel):
    """第二阶段入参：待确认 run_id + 用户编辑后的背景。"""

    run_id: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=36),
    ] = Field(..., description="第一阶段返回的 run_id")
    background: InterviewBackground = Field(..., description="确认后的面试背景")


class InterviewConfirmOut(BaseModel):
    """第二阶段出参：正式面试已创建。"""

    run_id: str = Field(..., description="面试准备运行 ID")
    interview_id: int = Field(..., description="新建面试记录 ID")
    session_id: int = Field(..., description="所属会话 ID")
    message_id: int = Field(..., description="面试入口消息 ID")
    status: Literal["confirmed"] = Field("confirmed", description="固定为 confirmed")


class InterviewOut(BaseModel):
    """面试详情：包含完整问答明细 qa_object。"""

    id: int = Field(..., description="面试记录 ID")
    session_id: int = Field(..., description="所属会话 ID")
    message_id: int = Field(..., description="入口消息 ID")
    qa_object: list[dict[str, Any]] = Field(..., description="问答明细列表")
    interview_host_prompt: str | None = Field(
        None, description="确认背景后重新生成的主考官提示词"
    )
    interview_duration: int = Field(..., description="累计面试时长（秒）")
    status: int = Field(..., description="面试状态：0=进行中，1=已结束，2=异常终止")
    created_at: int = Field(..., description="创建时间（Unix 秒）")
    updated_at: int = Field(..., description="更新时间（Unix 秒）")
