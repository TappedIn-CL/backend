"""make username nullable (set later after email/password signup)

Revision ID: 8f2e4c1a9b3d
Revises: e7b3c9d2f1a0
Create Date: 2026-04-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '8f2e4c1a9b3d'
down_revision: Union[str, None] = 'e7b3c9d2f1a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'users',
        'username',
        existing_type=sa.String(),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        'users',
        'username',
        existing_type=sa.String(),
        nullable=False,
    )