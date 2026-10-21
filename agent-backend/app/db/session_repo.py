"""数据库层：sessions 表读写仓储。

上层只经本模块读写会话；所有查询都带 user_id 条件，天然隔离用户数据。
"""

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select

from .models import ChatSession
from .session import SessionLocal


def _to_dict(obj: ChatSession) -> dict:
    """把 ORM 对象转成普通 dict 副本（列名 → 值）。"""
    return {column.name: getattr(obj, column.name) for column in obj.__table__.columns}


def insert(record: dict) -> dict:
    """插入会话，返回含数据库生成字段的完整副本。"""
    with SessionLocal() as session:
        obj = ChatSession(**record)
        session.add(obj)
        session.commit()
        session.refresh(obj)
        return _to_dict(obj)


def get(session_id: int) -> dict | None:
    """按 id 查询会话（内部使用，不校验归属）。"""
    with SessionLocal() as session:
        obj = session.get(ChatSession, session_id)
        return _to_dict(obj) if obj else None


def get_for_user(session_id: int, user_id: int) -> dict | None:
    """按 id + user_id 查询；不属于该用户时返回 None（对外统一 404）。"""
    with SessionLocal() as session:
        obj = session.scalar(
            select(ChatSession).where(
                ChatSession.id == session_id,
                ChatSession.user_id == user_id,
            )
        )
        return _to_dict(obj) if obj else None


def _filters(user_id: int, session_mode: int | None) -> list:
    """会话查询条件：用户隔离 + 可选的会话模式过滤。"""
    conditions = [ChatSession.user_id == user_id]
    if session_mode is not None:
        conditions.append(ChatSession.session_mode == session_mode)
    return conditions


def list_for_user(
    user_id: int, offset: int, limit: int, session_mode: int | None = None
) -> list[dict]:
    """分页返回用户的会话，最近创建的在前；可按会话模式过滤。"""
    with SessionLocal() as session:
        rows = session.scalars(
            select(ChatSession)
            .where(*_filters(user_id, session_mode))
            .order_by(ChatSession.created_at.desc(), ChatSession.id.desc())
            .offset(offset)
            .limit(limit)
        ).all()
        return [_to_dict(row) for row in rows]


def list_all_for_user(user_id: int) -> list[dict]:
    """返回用户全部会话（测试清理等内部场景使用）。"""
    with SessionLocal() as session:
        rows = session.scalars(
            select(ChatSession).where(ChatSession.user_id == user_id)
        ).all()
        return [_to_dict(row) for row in rows]


def count_for_user(user_id: int, session_mode: int | None = None) -> int:
    """统计用户会话总数（分页用）；可按会话模式过滤。"""
    with SessionLocal() as session:
        return session.scalar(
            select(func.count())
            .select_from(ChatSession)
            .where(*_filters(user_id, session_mode))
        ) or 0


def update_title(session_id: int, title: str) -> dict | None:
    """更新会话标题；会话不存在返回 None。"""
    with SessionLocal() as session:
        obj = session.get(ChatSession, session_id)
        if obj is None:
            return None
        obj.title = title
        session.commit()
        session.refresh(obj)
        return _to_dict(obj)


def delete(session_id: int) -> bool:
    """按 id 删除会话；返回是否删除成功。"""
    with SessionLocal() as session:
        result = session.execute(
            sa_delete(ChatSession).where(ChatSession.id == session_id)
        )
        session.commit()
        return result.rowcount > 0
