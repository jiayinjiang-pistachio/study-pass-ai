"""数据库层：prompt_templates 表读取与生效切换仓储。

「同一作用域仅一条生效」由回滚时的行锁事务保证：
先按作用域加锁（SELECT ... FOR UPDATE），再统一取消旧版本、激活目标版本。
公共通用模板固定作用域 (common, common)，与私有模板走同一套逻辑。
"""

from sqlalchemy import and_, select

from .models import PromptTemplate
from .session import SessionLocal


def _to_dict(obj: PromptTemplate) -> dict:
    """把 ORM 对象转成普通 dict 副本（列名 → 值）。"""
    return {column.name: getattr(obj, column.name) for column in obj.__table__.columns}


def _scope_filter(agent_name: str | None, scene: str):
    """作用域条件；保留 NULL 判断仅为兼容，业务层公共模板固定使用 common。"""
    if agent_name is None:
        return and_(PromptTemplate.agent_name.is_(None), PromptTemplate.scene == scene)
    return and_(
        PromptTemplate.agent_name == agent_name,
        PromptTemplate.scene == scene,
    )


def get_active(agent_name: str | None, scene: str) -> dict | None:
    """查询作用域内当前生效的版本；没有生效版本时返回 None。"""
    with SessionLocal() as session:
        obj = session.scalar(
            select(PromptTemplate).where(
                _scope_filter(agent_name, scene),
                PromptTemplate.is_active == 1,
            )
        )
        return _to_dict(obj) if obj else None


def list_active() -> list[dict]:
    """返回全部生效版本（启动预热缓存用）。"""
    with SessionLocal() as session:
        rows = session.scalars(
            select(PromptTemplate).where(PromptTemplate.is_active == 1)
        ).all()
        return [_to_dict(row) for row in rows]


def activate(template_id: int) -> dict | None:
    """把指定版本置为生效，并取消同作用域的其他版本；模板不存在返回 None。"""
    with SessionLocal() as session:
        obj = session.get(PromptTemplate, template_id)
        if obj is None:
            return None

        siblings = session.scalars(
            select(PromptTemplate)
            .where(_scope_filter(obj.agent_name, obj.scene))
            .with_for_update()
        ).all()
        for row in siblings:
            row.is_active = 0
        obj.is_active = 1

        session.commit()
        session.refresh(obj)
        return _to_dict(obj)
