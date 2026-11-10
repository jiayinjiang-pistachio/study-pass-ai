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


class VoiceRoomOut(BaseModel):
    """前端加入 RTC 房间所需的参数（RTC 未配置时 token 为空）。"""

    app_id: str | None = Field(None, description="RTC 应用 AppID，未配置时为 null")
    room_id: str = Field(..., description="RTC 房间 ID")
    user_id: str = Field(..., description="候选人 RTC 用户 ID")
    bot_user_id: str = Field(..., description="AI 面试官 RTC 用户 ID")
    task_id: str = Field(..., description="RTC AI 任务 ID")
    token: str | None = Field(None, description="入房 AccessToken，未配置时为 null")
    expire_at: int | None = Field(None, description="Token 过期时间（Unix 秒）")
    started: bool = Field(..., description="AI 面试官是否已成功启动")


class InterviewConfirmOut(BaseModel):
    """第二阶段出参：正式面试已创建。"""

    run_id: str = Field(..., description="面试准备运行 ID")
    interview_id: int = Field(..., description="新建面试记录 ID")
    session_id: int = Field(..., description="所属会话 ID")
    message_id: int = Field(..., description="面试入口消息 ID")
    status: Literal["confirmed"] = Field("confirmed", description="固定为 confirmed")
    voice: VoiceRoomOut = Field(..., description="前端加入 RTC 房间的参数")


class VoiceFinishIn(BaseModel):
    """挂断语音面试入参：最终问答明细与时长。"""

    qa_object: list[dict[str, Any]] = Field(
        default_factory=list, description="最终问答明细列表"
    )
    interview_duration: int = Field(0, ge=0, description="本次面试累计时长（秒）")


class InterviewVoiceFinishOut(BaseModel):
    """挂断语音面试出参：面试已结束。"""

    interview_id: int = Field(..., description="面试记录 ID")
    session_id: int = Field(..., description="所属会话 ID")
    status: int = Field(..., description="面试状态：1=已结束")
    interview_duration: int = Field(..., description="累计面试时长（秒）")
    qa_count: int = Field(..., description="保存的问答条数")


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
