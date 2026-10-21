"""add chat segments/status/interview_id and interview user_id

Revision ID: 0004
Revises: 1e4a0ff5a7a1
Create Date: 2026-10-21

会话与聊天接口需要的字段：
- chat_messages：附件段 request_segments / response_segments、消息状态 status、关联面试 interview_id；
- interviews：归属用户 user_id（查询面试详情时必须 interview_id + user_id 双条件）。
历史面试记录通过 session_id 关联 sessions 回填 user_id，再收紧为 NOT NULL。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, None] = "1e4a0ff5a7a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chat_messages", sa.Column("request_segments", sa.JSON(), nullable=True)
    )
    op.add_column(
        "chat_messages", sa.Column("response_segments", sa.JSON(), nullable=True)
    )
    op.add_column(
        "chat_messages",
        sa.Column("status", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "chat_messages", sa.Column("interview_id", sa.BigInteger(), nullable=True)
    )
    op.create_index(
        op.f("ix_chat_messages_interview_id"),
        "chat_messages",
        ["interview_id"],
        unique=False,
    )

    # 先加可空列并回填，避免历史数据导致 NOT NULL 约束失败
    op.add_column("interviews", sa.Column("user_id", sa.BigInteger(), nullable=True))
    op.execute(
        "UPDATE interviews i "
        "JOIN sessions s ON i.session_id = s.id "
        "SET i.user_id = s.user_id"
    )
    op.alter_column(
        "interviews", "user_id", existing_type=sa.BigInteger(), nullable=False
    )
    op.create_index(
        op.f("ix_interviews_user_id"), "interviews", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_interviews_user_id"), table_name="interviews")
    op.drop_column("interviews", "user_id")

    op.drop_index(op.f("ix_chat_messages_interview_id"), table_name="chat_messages")
    op.drop_column("chat_messages", "interview_id")
    op.drop_column("chat_messages", "status")
    op.drop_column("chat_messages", "response_segments")
    op.drop_column("chat_messages", "request_segments")
