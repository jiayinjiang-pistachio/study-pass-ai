"""数据库层：notes 表读写仓储。

笔记以 (user_id, source_run_id) 唯一；对上层只暴露 dict 副本。
"""

from sqlalchemy import select

from .models import Note
from .session import SessionLocal


def _to_dict(obj: Note) -> dict:
    """把 ORM 对象转成普通 dict；metadata 列对应 ORM 的 metadata_json。"""
    return {
        "id": obj.id,
        "user_id": obj.user_id,
        "session_id": obj.session_id,
        "source_run_id": obj.source_run_id,
        "note_type": obj.note_type,
        "title": obj.title,
        "content": obj.content,
        "tags": obj.tags,
        "metadata_json": obj.metadata_json,
        "created_at": obj.created_at,
        "updated_at": obj.updated_at,
    }


def get_by_user_and_run(user_id: int, source_run_id: str) -> dict | None:
    """按唯一约束字段查询；用于保存前判重与并发重复插入后的回查。"""
    with SessionLocal() as session:
        obj = session.scalar(
            select(Note).where(
                Note.user_id == user_id,
                Note.source_run_id == source_run_id,
            )
        )
        return _to_dict(obj) if obj else None


def insert(record: dict) -> dict:
    """插入一条笔记，返回含数据库生成字段的完整副本。"""
    with SessionLocal() as session:
        obj = Note(**record)
        session.add(obj)
        session.commit()
        session.refresh(obj)
        return _to_dict(obj)
