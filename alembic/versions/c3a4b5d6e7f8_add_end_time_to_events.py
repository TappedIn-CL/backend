"""add end_time to events

Revision ID: c3a4b5d6e7f8
Revises: a1f2e3d4c5b6
Create Date: 2026-05-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3a4b5d6e7f8'
down_revision: Union[str, None] = 'a1f2e3d4c5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('events', sa.Column('end_time', sa.DateTime(), nullable=True))
    op.create_index('ix_events_end_time', 'events', ['end_time'])


def downgrade() -> None:
    op.drop_index('ix_events_end_time', table_name='events')
    op.drop_column('events', 'end_time')
