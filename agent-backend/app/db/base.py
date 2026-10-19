"""ORM 基类：所有模型的公共父类，也是 Alembic autogenerate 感知表结构的入口。

模型必须继承本 Base 并 import 到 alembic/env.py，其表才会被纳入 Base.metadata，
否则 autogenerate 检测不到、不会生成对应迁移。
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """SQLAlchemy 2.0 声明式基类（使用 Mapped / mapped_column 风格）。"""
