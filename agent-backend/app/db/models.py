"""ORM 模型：数据库表结构的唯一声明处。

字段变更后执行 `scripts/db_sync.sh "说明"` 即可自动生成迁移并同步到数据库。
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.mysql import MEDIUMTEXT
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
    # 头像相对 URL（如 /uploads/users/1/<md5>.png）；注册时未上传则为 NULL
    avatar: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # server_default=func.now()：插入时由数据库自动填充当前时间，业务层无需传值
    create_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class ChatSession(Base):
    """会话表：一次学习 / 面试 / 笔记会话，归属单个用户。"""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 索引用于「按用户查会话列表」；外键默认不建索引，故显式 index=True
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), index=True, nullable=False
    )
    session_mode: Mapped[int] = mapped_column(
        Integer, nullable=False
    )  # 0=学习，1=面试，2=笔记
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    # Unix 秒时间戳；用 BIGINT 而非 INT，避免 2038 溢出
    created_at: Mapped[int] = mapped_column(
        BigInteger, server_default=text("(UNIX_TIMESTAMP())"), nullable=False
    )


class ChatMessage(Base):
    """消息表：会话内一问一答，含请求标识与所选子模式。"""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False
    )
    session_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sessions.id"), nullable=False
    )
    select_mode: Mapped[int] = mapped_column(
        Integer, nullable=False
    )  # 0=默认，1=知识精讲，2=刷题，3=简历优化，4=模拟面试，5=面试复盘
    # 按要求建索引：用于按请求标识回溯（如流式响应落库后关联前端请求）
    request_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    request_text: Mapped[str] = mapped_column(MEDIUMTEXT, nullable=False)
    response_text: Mapped[str] = mapped_column(MEDIUMTEXT, nullable=False)
    # 从附件中提取的完整文本，作为后续对话上下文；无附件或无法提取时为 NULL
    file_extracted_text: Mapped[str | None] = mapped_column(MEDIUMTEXT, nullable=True)
    created_at: Mapped[int] = mapped_column(
        BigInteger, server_default=text("(UNIX_TIMESTAMP())"), nullable=False
    )

    __table_args__ = (
        # 「按会话拉取并按时间排序」的查询路径依赖此复合索引；
        # 首列 session_id 同时覆盖按会话过滤，无需再单独建索引
        Index("ix_chat_messages_session_id_created_at", "session_id", "created_at"),
    )


class Interview(Base):
    """面试记录表：一次模拟面试的问答明细与状态，入口消息唯一。"""

    __tablename__ = "interviews"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sessions.id"), nullable=False
    )
    # 唯一：一条入口消息只能开启一次模拟面试
    message_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("chat_messages.id"), unique=True, nullable=False
    )
    # 一问一答列表：[{id, question, answer, created_at}, ...]，created_at 为 Unix 秒
    qa_object: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    interview_duration: Mapped[int] = mapped_column(
        Integer, server_default=text("0"), nullable=False
    )  # 累计面试时长（秒）
    status: Mapped[int] = mapped_column(
        Integer, server_default=text("0"), index=True, nullable=False
    )  # 0=进行中，1=已结束，2=异常终止
    created_at: Mapped[int] = mapped_column(
        BigInteger, server_default=text("(UNIX_TIMESTAMP())"), nullable=False
    )
    # 插入时自动填充，更新时由 SQLAlchemy 在 UPDATE 语句中写入 UNIX_TIMESTAMP()
    updated_at: Mapped[int] = mapped_column(
        BigInteger,
        server_default=text("(UNIX_TIMESTAMP())"),
        onupdate=text("UNIX_TIMESTAMP()"),
        nullable=False,
    )

    __table_args__ = (
        # 按会话查面试记录；message_id 已唯一，此处按需求补复合索引
        Index("ix_interviews_session_id_message_id", "session_id", "message_id"),
    )

