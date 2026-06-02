"""add source_url to events

Revision ID: c1d2e3f4a5b6
Revises: 9d1e2f3a4b5c
Create Date: 2026-05-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, None] = '9d1e2f3a4b5c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('events', sa.Column('source_url', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('events', 'source_url')
