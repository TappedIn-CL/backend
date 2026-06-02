"""merge kyle going_to_events/friendships + jason gcal heads

Revision ID: b7fa6abf03e4
Revises: a1b2c3d4e5f6, d8e9f0a1b2c3
Create Date: 2026-06-01 15:35:19.845510

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7fa6abf03e4'
down_revision: Union[str, None] = ('a1b2c3d4e5f6', 'd8e9f0a1b2c3')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
