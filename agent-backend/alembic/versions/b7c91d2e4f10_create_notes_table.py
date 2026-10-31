"""create notes table

Revision ID: b7c91d2e4f10
Revises: 76b0a08b3e79
Create Date: 2026-10-31 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


# revision identifiers, used by Alembic.
revision: str = 'b7c91d2e4f10'
down_revision: Union[str, None] = '76b0a08b3e79'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'notes',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('session_id', sa.BigInteger(), nullable=False),
        sa.Column('source_run_id', sa.String(length=36), nullable=False),
        sa.Column('note_type', sa.String(length=32), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('content', mysql.MEDIUMTEXT(), nullable=False),
        sa.Column('tags', sa.JSON(), nullable=False),
        sa.Column('metadata', sa.JSON(), nullable=False),
        sa.Column(
            'created_at',
            sa.BigInteger(),
            server_default=sa.text('(UNIX_TIMESTAMP())'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.BigInteger(),
            server_default=sa.text('(UNIX_TIMESTAMP())'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'user_id',
            'source_run_id',
            name='uq_notes_user_id_source_run_id',
        ),
    )
    op.create_index(
        op.f('ix_notes_session_id'), 'notes', ['session_id'], unique=False
    )
    op.create_index(
        op.f('ix_notes_note_type'), 'notes', ['note_type'], unique=False
    )
    op.create_index(
        'ix_notes_user_id_created_at',
        'notes',
        ['user_id', 'created_at'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_notes_user_id_created_at', table_name='notes')
    op.drop_index(op.f('ix_notes_note_type'), table_name='notes')
    op.drop_index(op.f('ix_notes_session_id'), table_name='notes')
    op.drop_table('notes')
