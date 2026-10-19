"""db：数据库层。基于 SQLAlchemy 2.0 + MySQL 持久化，表结构由 Alembic 管理。

- base.py      ORM 基类（Alembic 感知表结构的入口）
- models.py    表结构声明
- session.py   engine 与 Session 工厂
- user_repo.py users 表读写仓储（上层唯一入口）
"""
