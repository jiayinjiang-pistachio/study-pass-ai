"""数据库层：workflow_runs 表读写仓储。

工作流状态以 run_id 定位；对上层只暴露 dict 副本，不泄露 ORM 对象。
"""

from sqlalchemy import select

from .models import WorkflowRun
from .session import SessionLocal


def _to_dict(obj: WorkflowRun) -> dict:
    """把 ORM 对象转成普通 dict 副本（列名 → 值）。"""
    return {column.name: getattr(obj, column.name) for column in obj.__table__.columns}


def insert(record: dict) -> dict:
    """插入一次工作流运行，返回含数据库生成字段的完整副本。"""
    with SessionLocal() as session:
        obj = WorkflowRun(**record)
        session.add(obj)
        session.commit()
        session.refresh(obj)
        return _to_dict(obj)


def get_for_user(run_id: str, user_id: int) -> dict | None:
    """按 run_id + user_id 查询；不属于该用户时返回 None（对外统一 404）。"""
    with SessionLocal() as session:
        obj = session.scalar(
            select(WorkflowRun).where(
                WorkflowRun.run_id == run_id,
                WorkflowRun.user_id == user_id,
            )
        )
        return _to_dict(obj) if obj else None


def update(run_id: str, fields: dict) -> dict | None:
    """按 run_id 局部更新；运行不存在返回 None。

    updated_at 由 ORM 的 onupdate 自动刷新，调用方无需传。
    """
    with SessionLocal() as session:
        obj = session.scalar(select(WorkflowRun).where(WorkflowRun.run_id == run_id))
        if obj is None:
            return None
        for key, value in fields.items():
            setattr(obj, key, value)
        session.commit()
        session.refresh(obj)
        return _to_dict(obj)
