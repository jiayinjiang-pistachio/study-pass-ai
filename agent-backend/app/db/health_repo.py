"""数据库层：连通性探活。

供健康检查使用：只做一次最轻量的往返查询，确认数据库可连。
按约定（AGENTS.md §7），上层通过本模块函数访问，不直接碰 engine。
"""

from sqlalchemy import text

from .session import engine


def ping() -> None:
    """执行 `SELECT 1` 验证数据库连通性；连不上时抛出底层异常，由上层转成 503。"""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
