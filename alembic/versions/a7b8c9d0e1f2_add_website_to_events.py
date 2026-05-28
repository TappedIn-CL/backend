"""add website to events

Revision ID: a7b8c9d0e1f2
Revises: b2f3c4d5e6f7
Create Date: 2026-05-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, None] = 'b2f3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('events', sa.Column('website', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('events', 'website')