"""add going_to_events and friendships table

Revision ID: a1b2c3d4e5f6
Revises: e9b5d54d4b2c
Create Date: 2026-05-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'f40907e85090'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('going_to_events', postgresql.ARRAY(sa.String()), nullable=True),
    )

    op.create_table(
        'friendships',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('requester_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('addressee_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('status', sa.String(), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('now()')),
        sa.UniqueConstraint('requester_id', 'addressee_id', name='uq_friendship_pair'),
        sa.CheckConstraint("status IN ('pending', 'accepted')", name='ck_friendship_status'),
    )


def downgrade() -> None:
    op.drop_table('friendships')
    op.drop_column('users', 'going_to_events')
