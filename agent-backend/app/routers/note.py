"""路由层：笔记管理接口。

统一前缀 /api/notes，整组需登录；所有查询按令牌中的 user_id 隔离数据。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from ..schemas.note import NoteCreate, NoteListOut, NoteOut, NoteUpdate
from ..schemas.response import ResponseModel, ok
from ..services import note_service
from .deps import get_current_user

router = APIRouter(
    prefix="/api/notes",
    tags=["notes"],
    dependencies=[Depends(get_current_user)],
)

PageQuery = Annotated[int, Query(ge=1, description="页码，从 1 开始")]
PageSizeQuery = Annotated[int, Query(ge=1, le=100, description="每页条数，最大 100")]
NoteTypeQuery = Annotated[
    str | None,
    Query(
        min_length=1,
        max_length=32,
        description="按笔记类型过滤，如 learning_quiz / manual；不传返回全部",
    ),
]
KeywordQuery = Annotated[
    str | None,
    Query(
        min_length=1,
        max_length=100,
        description="在标题与正文中模糊搜索",
    ),
]


@router.get(
    "",
    response_model=ResponseModel[NoteListOut],
    summary="分页查询当前用户的笔记",
)
def list_notes(
    page: PageQuery = 1,
    page_size: PageSizeQuery = 20,
    note_type: NoteTypeQuery = None,
    keyword: KeywordQuery = None,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """按创建时间倒序返回笔记列表，支持类型过滤与关键词检索。"""
    return ok(
        note_service.list_notes(
            current_user["id"], page, page_size, note_type, keyword
        )
    )


@router.post(
    "",
    response_model=ResponseModel[NoteOut],
    summary="创建笔记",
)
def create_note(
    payload: NoteCreate,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """手动创建笔记；会话必须属于当前用户。"""
    return ok(note_service.create_note(current_user["id"], payload))


@router.get(
    "/{note_id}",
    response_model=ResponseModel[NoteOut],
    summary="查询笔记详情",
)
def get_note(
    note_id: int,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """只能查询自己的笔记；不存在或不属于当前用户返回 404。"""
    return ok(note_service.get_note(current_user["id"], note_id))


@router.put(
    "/{note_id}",
    response_model=ResponseModel[NoteOut],
    summary="更新笔记",
)
def update_note(
    note_id: int,
    payload: NoteUpdate,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """局部更新标题 / 正文 / 标签 / 附加信息。"""
    return ok(note_service.update_note(current_user["id"], note_id, payload))


@router.delete(
    "/{note_id}",
    response_model=ResponseModel[None],
    summary="删除笔记",
)
def delete_note(
    note_id: int,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """只能删除自己的笔记；不存在或不属于当前用户返回 404。"""
    note_service.delete_note(current_user["id"], note_id)
    return ok(None)
