"""数据库层：基于 SQLAlchemy 2.0 的 users 表读写仓储。

约定（见 AGENTS.md §7）：
- 上层（service）只能通过本模块函数读写，禁止直接访问 Session / ORM 对象；
- 对外一律返回普通 dict 副本，调用方拿不到会话内对象，避免误改与脏读；
- 函数名与返回值形状沿用原内存实现（insert/get/list_all/update/delete/find_by_username），
  使上层业务代码无需感知底层已从内存切换为 MySQL。
"""

from sqlalchemy import select

from .models import User
from .session import SessionLocal


def _to_dict(obj: User) -> dict:
    """把 ORM 对象转成普通 dict 副本（列名 → 值）。"""
    return {column.name: getattr(obj, column.name) for column in obj.__table__.columns}


def insert(record: dict) -> dict:
    """插入一条记录，返回完整记录副本（含数据库生成的 id 与 create_time）。"""
    with SessionLocal() as session:
        obj = User(**record)
        session.add(obj)
        session.commit()
        session.refresh(obj)  # 取回 server_default 生成的 create_time 与自增 id
        return _to_dict(obj)


def get(user_id: int) -> dict | None:
    """按 id 查询，未找到返回 None。"""
    with SessionLocal() as session:
        obj = session.get(User, user_id)
        return _to_dict(obj) if obj else None


def list_all() -> list[dict]:
    """返回全部记录（按 id 升序）。"""
    with SessionLocal() as session:
        rows = session.scalars(select(User).order_by(User.id)).all()
        return [_to_dict(row) for row in rows]


def update(user_id: int, fields: dict) -> dict | None:
    """按 id 局部更新字段，未找到返回 None。"""
    with SessionLocal() as session:
        obj = session.get(User, user_id)
        if obj is None:
            return None
        for key, value in fields.items():
            setattr(obj, key, value)
        session.commit()
        session.refresh(obj)
        return _to_dict(obj)


def delete(user_id: int) -> bool:
    """按 id 删除，返回是否删除成功。"""
    with SessionLocal() as session:
        obj = session.get(User, user_id)
        if obj is None:
            return False
        session.delete(obj)
        session.commit()
        return True


def find_by_username(username: str) -> dict | None:
    """按用户名精确查询（供业务层做唯一性校验）。"""
    with SessionLocal() as session:
        obj = session.scalar(select(User).where(User.username == username))
        return _to_dict(obj) if obj else None
