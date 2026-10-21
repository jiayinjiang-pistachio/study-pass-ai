"""校验层：面试详情出参模型。"""

from typing import Any

from pydantic import BaseModel, Field


class InterviewOut(BaseModel):
    """面试详情：包含完整问答明细 qa_object。"""

    id: int = Field(..., description="面试记录 ID")
    session_id: int = Field(..., description="所属会话 ID")
    message_id: int = Field(..., description="入口消息 ID")
    qa_object: list[dict[str, Any]] = Field(..., description="问答明细列表")
    interview_duration: int = Field(..., description="累计面试时长（秒）")
    status: int = Field(..., description="面试状态：0=进行中，1=已结束，2=异常终止")
    created_at: int = Field(..., description="创建时间（Unix 秒）")
    updated_at: int = Field(..., description="更新时间（Unix 秒）")
