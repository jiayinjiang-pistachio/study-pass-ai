"""校验层：会话的请求 / 响应模型。"""

from typing import Annotated

from pydantic import AliasChoices, BaseModel, Field, StringConstraints

SessionTitle = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]


class SessionCreate(BaseModel):
    """创建会话：标题 + 会话模式（0=学习，1=面试，2=笔记）。

    兼容 `session_model` 写法：需求文档中使用该字段名，数据库列名为 session_mode。
    """

    title: SessionTitle = Field(..., description="会话标题")
    session_mode: int = Field(
        ...,
        ge=0,
        le=2,
        validation_alias=AliasChoices("session_mode", "session_model"),
        description="会话模式：0=学习，1=面试，2=笔记",
    )


class SessionUpdate(BaseModel):
    """编辑会话：当前仅支持修改标题。"""

    title: SessionTitle = Field(..., description="新标题")


class SessionOut(BaseModel):
    """会话出参。"""

    id: int = Field(..., description="会话 ID")
    title: str = Field(..., description="会话标题")
    session_mode: int = Field(..., description="会话模式：0=学习，1=面试，2=笔记")
    created_at: int = Field(..., description="创建时间（Unix 秒）")


class SessionListOut(BaseModel):
    """会话分页出参。"""

    items: list[SessionOut] = Field(default_factory=list, description="当前页会话")
    total: int = Field(..., description="会话总数")
    page: int = Field(..., description="当前页码，从 1 开始")
    page_size: int = Field(..., description="每页条数")
