"""add doc_category to resources

Revision ID: 0005
Revises: a458fe295081
Create Date: 2026-10-25 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, None] = 'a458fe295081'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'resources',
        sa.Column('doc_category', sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('resources', 'doc_category')
