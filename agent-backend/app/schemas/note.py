"""校验层：笔记 CRUD 的请求 / 响应模型。"""

from typing import Annotated, Any

from pydantic import BaseModel, Field, StringConstraints

NoteTitle = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]
NoteContent = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200000)
]
NoteType = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)
]
NoteTag = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)
]


class NoteCreate(BaseModel):
    """手动创建笔记；source_run_id 由后端生成，前端无需传入。"""

    session_id: int = Field(..., ge=1, description="所属会话 ID")
    note_type: NoteType = Field("manual", description="笔记类型")
    title: NoteTitle = Field(..., description="笔记标题")
    content: NoteContent = Field(..., description="Markdown 正文")
    tags: list[NoteTag] = Field(
        default_factory=list, max_length=20, description="标签，最多 20 项"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="附加上下文，如 run_id / score"
    )


class NoteUpdate(BaseModel):
    """局部更新：只修改显式传入的字段。"""

    title: NoteTitle | None = None
    content: NoteContent | None = None
    tags: list[NoteTag] | None = Field(default=None, max_length=20)
    metadata: dict[str, Any] | None = None


class NoteOut(BaseModel):
    """笔记详情出参，不暴露 user_id。"""

    id: int = Field(..., description="笔记 ID")
    session_id: int = Field(..., description="所属会话 ID")
    source_run_id: str = Field(..., description="来源运行标识")
    note_type: str = Field(..., description="笔记类型")
    title: str = Field(..., description="笔记标题")
    content: str = Field(..., description="Markdown 正文")
    tags: list[str] = Field(default_factory=list, description="标签")
    metadata: dict[str, Any] = Field(default_factory=dict, description="附加信息")
    created_at: int = Field(..., description="创建时间（Unix 秒）")
    updated_at: int = Field(..., description="更新时间（Unix 秒）")


class NoteListItemOut(BaseModel):
    """列表出参：不返回正文，避免分页响应过大。"""

    id: int = Field(..., description="笔记 ID")
    session_id: int = Field(..., description="所属会话 ID")
    note_type: str = Field(..., description="笔记类型")
    title: str = Field(..., description="笔记标题")
    tags: list[str] = Field(default_factory=list, description="标签")
    created_at: int = Field(..., description="创建时间（Unix 秒）")
    updated_at: int = Field(..., description="更新时间（Unix 秒）")


class NoteListOut(BaseModel):
    """笔记分页出参。"""

    items: list[NoteListItemOut] = Field(default_factory=list, description="当前页笔记")
    total: int = Field(..., description="笔记总数")
    page: int = Field(..., description="当前页码，从 1 开始")
    page_size: int = Field(..., description="每页条数")
