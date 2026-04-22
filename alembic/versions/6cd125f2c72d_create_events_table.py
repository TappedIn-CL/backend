"""create events table

Revision ID: 6cd125f2c72d
Revises: e9b5d54d4b2c
Create Date: 2026-04-21 19:47:31.069808

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6cd125f2c72d'
down_revision: Union[str, None] = 'e9b5d54d4b2c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
