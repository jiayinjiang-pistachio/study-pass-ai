"""数据库层：user_profiles 表读写仓储。

一人一行（user_id 唯一），供提示词变量注入读取用户背景。
对外一律返回普通 dict 副本，不把会话内 ORM 对象交给调用方。
"""

from sqlalchemy import select

from .models import UserProfile
from .session import SessionLocal


def _to_dict(obj: UserProfile) -> dict:
    """把 ORM 对象转成普通 dict 副本（列名 → 值）。"""
    return {column.name: getattr(obj, column.name) for column in obj.__table__.columns}


def insert(user_id: int, fields: dict) -> dict:
    """插入一条背景资料，返回完整记录副本。"""
    with SessionLocal() as session:
        obj = UserProfile(user_id=user_id, **fields)
        session.add(obj)
        session.commit()
        session.refresh(obj)
        return _to_dict(obj)


def get_by_user_id(user_id: int) -> dict | None:
    """按 user_id 查询背景资料；未填写时返回 None。"""
    with SessionLocal() as session:
        obj = session.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
        return _to_dict(obj) if obj else None


def update(user_id: int, fields: dict) -> dict | None:
    """按 user_id 局部更新字段，未找到返回 None。"""
    with SessionLocal() as session:
        obj = session.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
        if obj is None:
            return None
        for key, value in fields.items():
            setattr(obj, key, value)
        session.commit()
        session.refresh(obj)
        return _to_dict(obj)


def upsert(user_id: int, fields: dict) -> dict:
    """存在则局部更新，不存在则插入；返回完整记录副本。"""
    with SessionLocal() as session:
        obj = session.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
        if obj is None:
            obj = UserProfile(user_id=user_id, **fields)
            session.add(obj)
        else:
            for key, value in fields.items():
                setattr(obj, key, value)
        session.commit()
        session.refresh(obj)
        return _to_dict(obj)


def delete(user_id: int) -> bool:
    """按 user_id 删除，返回是否删除成功。"""
    with SessionLocal() as session:
        obj = session.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
        if obj is None:
            return False
        session.delete(obj)
        session.commit()
        return True
