"""add avatar column to users

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-20

新增 users.avatar：保存头像的相对 URL，未上传时为 NULL。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "avatar")
