"""数据库层：chat_messages 表读写仓储。"""

from sqlalchemy import delete, func, select

from .models import ChatMessage
from .session import SessionLocal


def _to_dict(obj: ChatMessage) -> dict:
    """把 ORM 对象转成普通 dict 副本（列名 → 值）。"""
    return {column.name: getattr(obj, column.name) for column in obj.__table__.columns}


def insert(record: dict) -> dict:
    """插入一条消息，返回含数据库生成字段的完整副本。"""
    with SessionLocal() as session:
        obj = ChatMessage(**record)
        session.add(obj)
        session.commit()
        session.refresh(obj)
        return _to_dict(obj)


def get(message_id: int) -> dict | None:
    """按 id 查询消息，未找到返回 None。"""
    with SessionLocal() as session:
        obj = session.get(ChatMessage, message_id)
        return _to_dict(obj) if obj else None


def list_by_session(session_id: int, offset: int, limit: int) -> list[dict]:
    """分页返回会话内消息，按时间正序（符合聊天阅读顺序）。"""
    with SessionLocal() as session:
        rows = session.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
            .offset(offset)
            .limit(limit)
        ).all()
        return [_to_dict(row) for row in rows]


def list_all_by_session(session_id: int) -> list[dict]:
    """返回会话全部消息（级联删除前收集附件资源使用）。"""
    with SessionLocal() as session:
        rows = session.scalars(
            select(ChatMessage).where(ChatMessage.session_id == session_id)
        ).all()
        return [_to_dict(row) for row in rows]


def count_by_session(session_id: int) -> int:
    """统计会话消息总数（分页用）。"""
    with SessionLocal() as session:
        return session.scalar(
            select(func.count()).select_from(ChatMessage).where(
                ChatMessage.session_id == session_id
            )
        ) or 0


def delete_by_session(session_id: int) -> int:
    """删除会话下全部消息，返回删除行数。调用方需先删除关联 interviews。"""
    with SessionLocal() as session:
        result = session.execute(
            delete(ChatMessage).where(ChatMessage.session_id == session_id)
        )
        session.commit()
        return result.rowcount
