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
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.mysql import MEDIUMTEXT, TINYINT
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


class UserProfile(Base):
    """用户背景资料表：一人一行，供提示词变量注入使用。"""

    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 一个用户只有一份资料；唯一约束同时承担按 user_id 查询的索引
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    target_job: Mapped[str | None] = mapped_column(String(64), nullable=True)
    years_experience: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # JSON 数组，如 ["Python", "MySQL"]
    target_skills: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    weak_topics: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    # 长期记忆：由对话内容自动抽取，不通过资料 CRUD 接口写入
    learning_goal: Mapped[str | None] = mapped_column(String(255), nullable=True)
    learning_style: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # JSON 数组，如 ["Java 后端", "数据库原理"]
    interview_focus: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    # 滚动摘要：合并历次画像抽取结果，避免只保留最近一轮信息
    long_term_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[int] = mapped_column(
        BigInteger, server_default=text("(UNIX_TIMESTAMP())"), nullable=False
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
    # 只存附件段（file / image / audio）；聊天正文始终在 request_text / response_text
    request_segments: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    response_segments: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    # 本轮回答参考的知识片段索引：[{chunk_id, score}]；原文留在 knowledge_chunks，
    # 历史消息按 chunk_id 回查即可，避免重复保存知识块全文
    reference_sources: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    # 0=生成中，1=完成，2=失败；前端据此展示消息状态
    status: Mapped[int] = mapped_column(
        Integer, server_default=text("0"), nullable=False
    )
    # 该消息关联的面试记录；普通聊天为 NULL（不建外键，避免与 interviews.message_id 循环依赖）
    interview_id: Mapped[int | None] = mapped_column(
        BigInteger, index=True, nullable=True
    )
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
    # 归属用户：查询面试详情时必须同时校验 interview_id + user_id
    user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
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


class PromptTemplate(Base):
    """提示词模板表：按 (agent_name, scene) 维护独立版本链。

    公共通用模板固定 agent_name='common'、scene='common'；
    私有模板为智能体名 + 专属场景。同一作用域内只有一个 is_active=1 的版本。
    """

    __tablename__ = "prompt_templates"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 公共通用模板固定 common；私有模板为 AGENT_CONFIG 中的智能体名
    agent_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 公共通用模板固定 common；私有模板为智能体专属场景（如 study / interview）
    scene: Mapped[str] = mapped_column(String(64), nullable=False)
    template_type: Mapped[int] = mapped_column(
        TINYINT, nullable=False
    )  # 1=私有，2=公共
    template_content: Mapped[str] = mapped_column(MEDIUMTEXT, nullable=False)
    # JSON 数组字符串，如 ["question", "language"]；无变量时为 NULL
    variables: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # 同一作用域内自增，从 1 开始
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    # 0=未生效，1=生效；同一 (agent_name, scene) 至多一条生效
    is_active: Mapped[int] = mapped_column(
        TINYINT, server_default=text("0"), nullable=False
    )
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[int] = mapped_column(
        BigInteger, server_default=text("(UNIX_TIMESTAMP())"), nullable=False
    )

    __table_args__ = (
        # 作用域查询（当前生效版本 / 版本链）与单一生效约束的应用层校验都依赖此索引
        Index("ix_prompt_templates_agent_scene", "agent_name", "scene"),
        Index(
            "ix_prompt_templates_agent_scene_active",
            "agent_name",
            "scene",
            "is_active",
        ),
        # 版本号由数据库兜底防重；单一生效由仓储层事务行锁保证
        UniqueConstraint(
            "agent_name", "scene", "version", name="uk_prompt_agent_scene_version"
        ),
    )


class KnowledgeChunk(Base):
    """知识库切片原文表：Qdrant 只存向量，原文与统计字段落 MySQL。

    vector_id 与 Qdrant Point id 相同，检索命中向量后按它回表取原文。
    """

    __tablename__ = "knowledge_chunks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 与 Qdrant Point id 一一对应；全局唯一，避免两张存储出现错配
    vector_id: Mapped[str] = mapped_column(
        String(36), unique=True, index=True, nullable=False
    )
    # 归属资源：资源删除时级联清理切片，避免残留孤立原文
    resource_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("resources.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    # 在本次入库切片序列中的位置，从 0 开始
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(MEDIUMTEXT, nullable=False)
    # 字符数，便于统计切片长度分布；与 text 同时写入
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    create_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # 同一资源的切片序号唯一；重灌时按 resource_id 整体替换
        UniqueConstraint(
            "resource_id", "chunk_index", name="uk_chunk_resource_index"
        ),
    )


class Resource(Base):
    """资源元数据表：统一管理文件 / 图片 / 音频，原文件落在 MinIO。"""

    __tablename__ = "resources"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    resource_type: Mapped[int] = mapped_column(
        TINYINT, nullable=False
    )  # 0=文件，1=图片，2=音频
    storage_scene: Mapped[int] = mapped_column(
        TINYINT, server_default=text("0"), nullable=False
    )  # 0=长期（1个月），1=短期（2小时），2=只提取内容不存原文件
    upload_purpose: Mapped[int] = mapped_column(
        TINYINT, server_default=text("0"), nullable=False
    )  # 0=普通资源，1=用户头像
    # 文档业务类型：resume / study_material / general；仅 resource_type=0（文档）有意义
    doc_category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # 文件内容 MD5；与 user_id 组成唯一键，实现用户级去重
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # minio:/{bucket}/{object_key}；storage_scene=2 时为空串（不落对象）
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expire_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    create_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # 数据库兜底去重：同一用户相同内容只保留一条资源记录
        UniqueConstraint("file_hash", "user_id", name="uk_file_hash_user_id"),
    )

