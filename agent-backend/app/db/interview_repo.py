"""数据库层：interviews 表读写仓储。"""

from sqlalchemy import delete, select

from .models import Interview
from .session import SessionLocal


def _to_dict(obj: Interview) -> dict:
    """把 ORM 对象转成普通 dict 副本（列名 → 值）。"""
    return {column.name: getattr(obj, column.name) for column in obj.__table__.columns}


def insert(record: dict) -> dict:
    """插入面试记录，返回含数据库生成字段的完整副本。"""
    with SessionLocal() as session:
        obj = Interview(**record)
        session.add(obj)
        session.commit()
        session.refresh(obj)
        return _to_dict(obj)


def get(interview_id: int) -> dict | None:
    """按 id 查询面试记录，未找到返回 None。"""
    with SessionLocal() as session:
        obj = session.get(Interview, interview_id)
        return _to_dict(obj) if obj else None


def get_for_user(interview_id: int, user_id: int) -> dict | None:
    """按 id + user_id 查询，防止越权读取他人的面试记录。"""
    with SessionLocal() as session:
        obj = session.scalar(
            select(Interview).where(
                Interview.id == interview_id,
                Interview.user_id == user_id,
            )
        )
        return _to_dict(obj) if obj else None


def delete_by_session(session_id: int) -> int:
    """删除会话关联的全部面试记录，返回删除行数。"""
    with SessionLocal() as session:
        result = session.execute(
            delete(Interview).where(Interview.session_id == session_id)
        )
        session.commit()
        return result.rowcount
