"""数据库层：workflow_runs 表读写仓储。

工作流状态以 run_id 定位；对上层只暴露 dict 副本，不泄露 ORM 对象。
"""

from sqlalchemy import select, update as sql_update

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


def get_latest_for_session(
    user_id: int,
    session_id: int,
    *,
    workflow_type: str | None = None,
    status: str | None = None,
) -> dict | None:
    """按会话取最近一次运行；可选按流程类型 / 状态收窄。

    调度上下文用它解析「刚才那套题」「最近一次测评」等指代。
    """
    conditions = [
        WorkflowRun.user_id == user_id,
        WorkflowRun.session_id == session_id,
    ]
    if workflow_type is not None:
        conditions.append(WorkflowRun.workflow_type == workflow_type)
    if status is not None:
        conditions.append(WorkflowRun.status == status)
    with SessionLocal() as session:
        obj = session.scalar(
            select(WorkflowRun)
            .where(*conditions)
            .order_by(WorkflowRun.created_at.desc(), WorkflowRun.id.desc())
            .limit(1)
        )
        return _to_dict(obj) if obj else None


def claim_status(
    run_id: str, user_id: int, expected_status: str, new_status: str
) -> bool:
    """原子地把 run 从 expected_status 切到 new_status。

    以 `UPDATE ... WHERE status=expected` 的条件更新保证并发确认时只有一次成功；
    返回是否抢到状态迁移。
    """
    with SessionLocal() as session:
        result = session.execute(
            sql_update(WorkflowRun)
            .where(
                WorkflowRun.run_id == run_id,
                WorkflowRun.user_id == user_id,
                WorkflowRun.status == expected_status,
            )
            .values(status=new_status)
        )
        session.commit()
        return result.rowcount == 1


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
