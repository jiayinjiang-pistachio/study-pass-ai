"""校验层：聊天消息出参模型。

正文与附件分离：request_text / response_text 为聊天正文，
request_segments / response_segments 只包含附件段（file / image / audio）。
"""

from typing import Literal

from pydantic import BaseModel, Field


class SegmentOut(BaseModel):
    """附件段：指向 resources 表的一条元数据。"""

    type: Literal["file", "image", "audio"] = Field(..., description="附件类型")
    resource_id: int = Field(..., description="resources 表主键")
    file_name: str | None = Field(None, description="原始文件名（可选快照）")
    url: str | None = Field(None, description="访问地址（可选快照）")


class SourceOut(BaseModel):
    """回答参考的知识库片段：正文按 chunk_id 回查，不在消息表重复存储。"""

    chunk_id: str = Field(..., description="知识片段 ID（Qdrant Point id / vector_id）")
    resource_id: int | None = Field(None, description="来源资源 ID；片段已删除时为 null")
    chunk_index: int | None = Field(None, description="片段在资源内的序号；已删除时为 null")
    file_name: str | None = Field(None, description="来源文件名；片段已删除时为 null")
    score: float | None = Field(None, description="检索相似度分数")
    text: str = Field(..., description="片段原文；片段已删除时为提示文案")


class MessageOut(BaseModel):
    """单条聊天记录：一问一答 + 附件 + 状态/面试关联 + 参考来源。"""

    id: int = Field(..., description="消息 ID")
    request_text: str = Field(..., description="用户提问正文")
    response_text: str = Field(..., description="AI 回复正文")
    request_segments: list[SegmentOut] = Field(
        default_factory=list, description="用户提问附件段"
    )
    response_segments: list[SegmentOut] = Field(
        default_factory=list, description="AI 回复附件段"
    )
    sources: list[SourceOut] = Field(
        default_factory=list,
        description="回答参考的知识库片段（按 reference_sources 回查重建）",
    )
    status: int = Field(..., description="消息状态：0=生成中，1=完成，2=失败")
    interview_id: int | None = Field(
        None, description="关联面试记录 ID；普通聊天为 null"
    )
    created_at: int = Field(..., description="创建时间（Unix 秒）")


class MessageListOut(BaseModel):
    """聊天消息分页出参。"""

    items: list[MessageOut] = Field(default_factory=list, description="当前页消息")
    total: int = Field(..., description="消息总数")
    page: int = Field(..., description="当前页码，从 1 开始")
    page_size: int = Field(..., description="每页条数")
