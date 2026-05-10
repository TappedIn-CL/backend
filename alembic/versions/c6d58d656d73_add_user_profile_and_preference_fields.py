"""add user profile and preference fields

Revision ID: c6d58d656d73
Revises: 8c9d0a1b2c3e
Create Date: 2026-05-05 20:04:09.710804

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c6d58d656d73'
down_revision: Union[str, None] = '8c9d0a1b2c3e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
