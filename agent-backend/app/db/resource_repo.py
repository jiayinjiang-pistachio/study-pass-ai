"""数据库层：resources 表读写仓储。

约定（见 AGENTS.md §7）：上层只经本模块读写，对外返回普通 dict 副本。
"""

from datetime import datetime

from sqlalchemy import select

from .models import Resource
from .session import SessionLocal


def _to_dict(obj: Resource) -> dict:
    """把 ORM 对象转成普通 dict 副本（列名 → 值）。"""
    return {column.name: getattr(obj, column.name) for column in obj.__table__.columns}


def get(resource_id: int) -> dict | None:
    """按 id 查询，未找到返回 None。"""
    with SessionLocal() as session:
        obj = session.get(Resource, resource_id)
        return _to_dict(obj) if obj else None


def find_by_hash(user_id: int, file_hash: str) -> dict | None:
    """按 (user_id, file_hash) 查询，用于上传前的用户级去重预查。"""
    with SessionLocal() as session:
        obj = session.scalar(
            select(Resource).where(
                Resource.user_id == user_id,
                Resource.file_hash == file_hash,
            )
        )
        return _to_dict(obj) if obj else None


def insert(record: dict) -> dict:
    """插入一条资源记录，返回完整副本。

    唯一键 (file_hash, user_id) 冲突时抛 IntegrityError，由业务层兜底。
    """
    with SessionLocal() as session:
        obj = Resource(**record)
        session.add(obj)
        session.commit()
        session.refresh(obj)
        return _to_dict(obj)


def delete(resource_id: int) -> bool:
    """按 id 删除，返回是否删除成功。"""
    with SessionLocal() as session:
        obj = session.get(Resource, resource_id)
        if obj is None:
            return False
        session.delete(obj)
        session.commit()
        return True


def list_by_user(user_id: int) -> list[dict]:
    """返回某用户的全部资源记录（测试清理与排查用）。"""
    with SessionLocal() as session:
        rows = session.scalars(
            select(Resource).where(Resource.user_id == user_id)
        ).all()
        return [_to_dict(row) for row in rows]


def delete_by_user(user_id: int) -> int:
    """删除某用户的全部资源记录，返回删除行数（测试清理用）。"""
    with SessionLocal() as session:
        rows = session.scalars(
            select(Resource).where(Resource.user_id == user_id)
        ).all()
        for row in rows:
            session.delete(row)
        session.commit()
        return len(rows)


def list_expired(now: datetime) -> list[dict]:
    """返回 expire_time 已到期的资源记录（expire_time 为空表示永不过期）。"""
    with SessionLocal() as session:
        rows = session.scalars(
            select(Resource).where(
                Resource.expire_time.is_not(None),
                Resource.expire_time <= now,
            )
        ).all()
        return [_to_dict(row) for row in rows]
