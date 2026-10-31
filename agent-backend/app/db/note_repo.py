"""数据库层：notes 表读写仓储。

笔记以 (user_id, source_run_id) 唯一；对上层只暴露 dict 副本。
"""

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, or_, select

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


def get_for_user(note_id: int, user_id: int) -> dict | None:
    """按 id + user_id 查询；不属于该用户返回 None（对外统一 404）。"""
    with SessionLocal() as session:
        obj = session.scalar(
            select(Note).where(Note.id == note_id, Note.user_id == user_id)
        )
        return _to_dict(obj) if obj else None


def _filters(
    user_id: int, note_type: str | None, keyword: str | None
) -> list:
    """笔记查询条件：用户隔离 + 可选类型过滤 + 标题 / 正文关键词。"""
    conditions = [Note.user_id == user_id]
    if note_type is not None:
        conditions.append(Note.note_type == note_type)
    if keyword:
        # autoescape 转义 % / _，避免用户输入被当作通配符
        conditions.append(
            or_(
                Note.title.contains(keyword, autoescape=True),
                Note.content.contains(keyword, autoescape=True),
            )
        )
    return conditions


def list_for_user(
    user_id: int,
    offset: int,
    limit: int,
    note_type: str | None = None,
    keyword: str | None = None,
) -> list[dict]:
    """分页返回用户的笔记，最近创建的在前。"""
    with SessionLocal() as session:
        rows = session.scalars(
            select(Note)
            .where(*_filters(user_id, note_type, keyword))
            .order_by(Note.created_at.desc(), Note.id.desc())
            .offset(offset)
            .limit(limit)
        ).all()
        return [_to_dict(row) for row in rows]


def count_for_user(
    user_id: int, note_type: str | None = None, keyword: str | None = None
) -> int:
    """统计用户笔记总数（分页用）。"""
    with SessionLocal() as session:
        return session.scalar(
            select(func.count())
            .select_from(Note)
            .where(*_filters(user_id, note_type, keyword))
        ) or 0


def insert(record: dict) -> dict:
    """插入一条笔记，返回含数据库生成字段的完整副本。"""
    with SessionLocal() as session:
        obj = Note(**record)
        session.add(obj)
        session.commit()
        session.refresh(obj)
        return _to_dict(obj)


def update(note_id: int, record: dict) -> dict | None:
    """按 id 更新笔记；不存在返回 None。"""
    with SessionLocal() as session:
        obj = session.get(Note, note_id)
        if obj is None:
            return None
        for field, value in record.items():
            setattr(obj, field, value)
        session.commit()
        session.refresh(obj)
        return _to_dict(obj)


def delete(note_id: int) -> bool:
    """按 id 删除笔记；返回是否删除成功。"""
    with SessionLocal() as session:
        result = session.execute(sa_delete(Note).where(Note.id == note_id))
        session.commit()
        return result.rowcount > 0
