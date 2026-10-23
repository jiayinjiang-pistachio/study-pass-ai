"""校验层：流式聊天入参模型。

正文与附件分离（与 chat_messages 表一致）：request_text 是提问正文，
request_segments 只放附件段，指向已上传的 resources 记录。
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class SegmentIn(BaseModel):
    """请求附件段：只接受已上传资源的引用。"""

    type: Literal["file", "image", "audio"] = Field(..., description="附件类型")
    resource_id: int = Field(..., gt=0, description="resources 表主键")
    file_name: str | None = Field(None, max_length=255, description="原始文件名（可选快照）")
    url: str | None = Field(None, max_length=512, description="访问地址（可选快照）")


class StreamChatIn(BaseModel):
    """流式对话入参：提问正文 + 子模式 + 可选附件。"""

    request_text: str = Field(
        ..., min_length=1, max_length=20000, description="用户提问正文"
    )
    select_mode: int = Field(
        0,
        ge=0,
        le=5,
        description="子模式：0=默认，1=知识精讲，2=刷题，3=简历优化，4=模拟面试，5=面试复盘",
    )
    request_id: str | None = Field(
        None,
        max_length=64,
        description="前端请求标识；不传时由后端生成，用于流式落库后回溯",
    )
    request_segments: list[SegmentIn] = Field(
        default_factory=list, description="提问携带的附件段"
    )

    @field_validator("request_text")
    @classmethod
    def _strip_request_text(cls, value: str) -> str:
        """去掉首尾空白；纯空白视为非法提问。"""
        text = value.strip()
        if not text:
            raise ValueError("提问内容不能为空")
        return text

    @field_validator("request_id")
    @classmethod
    def _normalize_request_id(cls, value: str | None) -> str | None:
        """空串按未传处理，避免落库出现无意义的空标识。"""
        if value is None:
            return None
        return value.strip() or None
