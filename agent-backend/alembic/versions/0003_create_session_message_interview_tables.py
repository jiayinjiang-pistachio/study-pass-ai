"""create sessions / chat_messages / interviews tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-20

新增会话、消息、面试记录三张表及所需外键 / 索引：
- sessions：按用户查会话，user_id 建索引；
- chat_messages：request_id 索引，session_id + created_at 复合索引支撑按会话按时间拉取；
- interviews：message_id 唯一（一条入口消息只开一次面试），session_id + message_id 复合索引。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("session_mode", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.BigInteger(),
            server_default=sa.text("(UNIX_TIMESTAMP())"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sessions_user_id"), "sessions", ["user_id"], unique=False)

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("session_id", sa.BigInteger(), nullable=False),
        sa.Column("select_mode", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("request_text", mysql.MEDIUMTEXT(), nullable=False),
        sa.Column("response_text", mysql.MEDIUMTEXT(), nullable=False),
        sa.Column(
            "created_at",
            sa.BigInteger(),
            server_default=sa.text("(UNIX_TIMESTAMP())"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_chat_messages_request_id"),
        "chat_messages",
        ["request_id"],
        unique=False,
    )
    op.create_index(
        "ix_chat_messages_session_id_created_at",
        "chat_messages",
        ["session_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "interviews",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("qa_object", sa.JSON(), nullable=False),
        sa.Column(
            "interview_duration",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("status", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.BigInteger(),
            server_default=sa.text("(UNIX_TIMESTAMP())"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.BigInteger(),
            server_default=sa.text("(UNIX_TIMESTAMP())"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["message_id"], ["chat_messages.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
        # 一条入口消息只能对应一条面试记录
        sa.UniqueConstraint("message_id"),
    )
    op.create_index(
        "ix_interviews_session_id_message_id",
        "interviews",
        ["session_id", "message_id"],
        unique=False,
    )
    op.create_index(op.f("ix_interviews_status"), "interviews", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_interviews_status"), table_name="interviews")
    op.drop_index("ix_interviews_session_id_message_id", table_name="interviews")
    op.drop_table("interviews")
    op.drop_index("ix_chat_messages_session_id_created_at", table_name="chat_messages")
    op.drop_index(op.f("ix_chat_messages_request_id"), table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index(op.f("ix_sessions_user_id"), table_name="sessions")
    op.drop_table("sessions")
