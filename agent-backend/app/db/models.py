"""ORM 模型：数据库表结构的唯一声明处。

字段变更后执行 `scripts/db_sync.sh "说明"` 即可自动生成迁移并同步到数据库。
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class User(Base):
    """用户表：id 自增主键、username 唯一索引、password 哈希、create_time 自动填充。"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # unique=True + index=True：在 username 上建唯一索引，兼作登录查询的加速索引
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    # 只存 bcrypt 哈希，绝不落明文（见 app/core/security.py）
    password: Mapped[str] = mapped_column(String(255), nullable=False)
    # server_default=func.now()：插入时由数据库自动填充当前时间，业务层无需传值
    create_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
