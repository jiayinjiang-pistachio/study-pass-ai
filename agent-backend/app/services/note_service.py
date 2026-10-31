"""业务层：笔记保存与管理。

学习测评笔记按 (user_id, source_run_id) 幂等写入并回写运行状态；
笔记 CRUD 的所有读写都按 user_id 隔离。
"""

import logging
import uuid
from typing import Any

from fastapi import status
from sqlalchemy.exc import IntegrityError

from ..core.exceptions import BusinessException
from ..db import note_repo, session_repo, workflow_run_repo
from ..schemas.note import NoteCreate, NoteUpdate

logger = logging.getLogger(__name__)

NOTE_TYPE_LEARNING_QUIZ = "learning_quiz"
NOTE_STATUS_SAVED = "saved"
NOTE_STATUS_EXISTING = "existing"


class NoteService:
    """笔记保存服务；不负责内容生成，只处理幂等落库与运行状态回写。"""

    def save_learning_quiz_note(
        self,
        user_id: int,
        session_id: int,
        source_run_id: str,
        archive: dict[str, Any],
    ) -> dict[str, Any]:
        """保存测评笔记；同一用户同一运行重复调用返回已有笔记。"""
        title = str(archive.get("title") or "").strip()
        content = str(archive.get("content") or "").strip()
        if not title or not content:
            raise BusinessException(
                "笔记标题或正文为空，无法保存",
                http_status=status.HTTP_400_BAD_REQUEST,
                detail=f"run_id={source_run_id}",
            )

        note = note_repo.get_by_user_and_run(user_id, source_run_id)
        note_status = NOTE_STATUS_EXISTING

        if note is None:
            try:
                note = note_repo.insert(
                    {
                        "user_id": user_id,
                        "session_id": session_id,
                        "source_run_id": source_run_id,
                        "note_type": NOTE_TYPE_LEARNING_QUIZ,
                        "title": title,
                        "content": content,
                        "tags": archive.get("tags") or [],
                        "metadata_json": archive.get("metadata") or {},
                    }
                )
                note_status = NOTE_STATUS_SAVED
            except IntegrityError:
                # 并发保存同一运行时由唯一约束兜底：回查已写入的那一条
                note = note_repo.get_by_user_and_run(user_id, source_run_id)
                if note is None:
                    raise
                note_status = NOTE_STATUS_EXISTING

        self._write_back_run_state(user_id, source_run_id, note["id"], note_status)
        return {"note_id": note["id"], "note_status": note_status}

    def _write_back_run_state(
        self, user_id: int, source_run_id: str, note_id: int, note_status: str
    ) -> None:
        """只往 state_json 补 note_id / note_status，避免把整份笔记塞进运行记录。"""
        row = workflow_run_repo.get_for_user(source_run_id, user_id)
        if row is None:
            logger.warning("笔记已保存但运行记录不存在 | run_id=%s", source_run_id)
            return

        state = dict(row.get("state_json") or {})
        state["note_id"] = note_id
        # 一旦笔记落库就是 saved，重复保存不能把它降级成 existing
        if state.get("note_status") != NOTE_STATUS_SAVED:
            state["note_status"] = note_status
        try:
            workflow_run_repo.update(source_run_id, {"state_json": state})
        except Exception:
            # 笔记已落库，回写失败只告警，避免把成功归档标记成失败
            logger.warning(
                "笔记状态回写失败 | run_id=%s note_id=%s",
                source_run_id,
                note_id,
                exc_info=True,
            )


def _to_out(note: dict, *, include_content: bool = True) -> dict[str, Any]:
    """组装出参，不暴露 user_id；列表场景可省略大字段 content。"""
    data = {
        "id": note["id"],
        "session_id": note["session_id"],
        "source_run_id": note["source_run_id"],
        "note_type": note["note_type"],
        "title": note["title"],
        "tags": note["tags"] or [],
        "metadata": note["metadata_json"] or {},
        "created_at": note["created_at"],
        "updated_at": note["updated_at"],
    }
    if include_content:
        data["content"] = note["content"]
    return data


def _get_owned_note(user_id: int, note_id: int) -> dict:
    """取当前用户的笔记；不存在或不属于该用户统一 404。"""
    note = note_repo.get_for_user(note_id, user_id)
    if note is None:
        raise BusinessException(
            "笔记不存在",
            http_status=status.HTTP_404_NOT_FOUND,
            detail=f"note_id={note_id} user_id={user_id}",
        )
    return note


def list_notes(
    user_id: int,
    page: int,
    page_size: int,
    note_type: str | None = None,
    keyword: str | None = None,
) -> dict:
    """分页返回当前用户的笔记，可按类型过滤、按标题 / 正文关键词检索。"""
    keyword = keyword.strip() if keyword else None
    offset = (page - 1) * page_size
    return {
        "items": [
            _to_out(row, include_content=False)
            for row in note_repo.list_for_user(
                user_id, offset, page_size, note_type, keyword
            )
        ],
        "total": note_repo.count_for_user(user_id, note_type, keyword),
        "page": page,
        "page_size": page_size,
    }


def create_note(user_id: int, payload: NoteCreate) -> dict:
    """手动创建笔记；会话必须属于当前用户。"""
    if session_repo.get_for_user(payload.session_id, user_id) is None:
        raise BusinessException(
            "会话不存在",
            http_status=status.HTTP_404_NOT_FOUND,
            detail=f"session_id={payload.session_id} user_id={user_id}",
        )

    note = note_repo.insert(
        {
            "user_id": user_id,
            "session_id": payload.session_id,
            "source_run_id": str(uuid.uuid4()),
            "note_type": payload.note_type,
            "title": payload.title,
            "content": payload.content,
            "tags": payload.tags,
            "metadata_json": payload.metadata,
        }
    )
    return _to_out(note)


def get_note(user_id: int, note_id: int) -> dict:
    """读取单条笔记详情；只能读取自己的笔记。"""
    return _to_out(_get_owned_note(user_id, note_id))


def update_note(user_id: int, note_id: int, payload: NoteUpdate) -> dict:
    """局部更新笔记；只修改显式传入的字段。"""
    _get_owned_note(user_id, note_id)

    fields = payload.model_dump(exclude_unset=True, exclude_none=True)
    if "metadata" in fields:
        # ORM 属性为 metadata_json，列名仍是 metadata
        fields["metadata_json"] = fields.pop("metadata")
    if not fields:
        return _to_out(_get_owned_note(user_id, note_id))

    note = note_repo.update(note_id, fields)
    if note is None:
        raise BusinessException(
            "笔记不存在",
            http_status=status.HTTP_404_NOT_FOUND,
            detail=f"note_id={note_id}",
        )
    return _to_out(note)


def delete_note(user_id: int, note_id: int) -> None:
    """删除自己的笔记。"""
    _get_owned_note(user_id, note_id)
    note_repo.delete(note_id)
