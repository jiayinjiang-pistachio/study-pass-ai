"""数据库会话：创建引擎与 Session 工厂，供 db 层各仓储函数使用。

采用同步 SQLAlchemy + PyMySQL，与现有同步路由（def，非 async def）保持一致。
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ..core.config import get_mysql_url

# create_engine 不会立即建连（惰性），但连接串缺失会在导入阶段即报错，定位清晰
engine = create_engine(
    get_mysql_url(),
    pool_pre_ping=True,  # 取连接前先 ping，规避 MySQL 8 小时空闲断连
    pool_recycle=3600,   # 连接存活上限 1 小时，主动回收
    future=True,
)

# expire_on_commit=False：commit 后对象属性仍可读，便于组装返回的 dict
# autoflush=False：避免查询前隐式 flush，写入时机由仓储函数显式控制
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
