"""add latitude and longitude to events

Revision ID: b2f3c4d5e6f7
Revises: 43b41105019a
Create Date: 2026-05-14 19:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2f3c4d5e6f7'
down_revision: Union[str, None] = '43b41105019a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('events', sa.Column('latitude', sa.Float(), nullable=True))
    op.add_column('events', sa.Column('longitude', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('events', 'longitude')
    op.drop_column('events', 'latitude')
