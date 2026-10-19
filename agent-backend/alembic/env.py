"""Alembic 运行环境：注入连接串、暴露模型元数据，使 autogenerate 能感知表结构。

与项目约定的衔接：
- 连接串从环境变量 MYSQL_URL 读取（复用 app.core.config），不写进 alembic.ini；
- target_metadata 指向 app.db.base.Base.metadata，故必须先 import 所有模型模块。
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# 让 app 包可被导入（alembic.ini 的 prepend_sys_path=. 已把仓库根加入 sys.path）
from app.core.config import get_mysql_url
from app.db.base import Base

# 关键：导入模型模块，把表注册进 Base.metadata，否则 autogenerate 检测不到
import app.db.models  # noqa: F401

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# 用环境变量里的连接串覆盖 alembic.ini（避免口令入库）
config.set_main_option("sqlalchemy.url", get_mysql_url())

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# autogenerate 依据的模型元数据
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
