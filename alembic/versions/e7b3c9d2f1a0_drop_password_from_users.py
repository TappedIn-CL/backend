"""drop password from users (auth handled by Supabase)

Revision ID: e7b3c9d2f1a0
Revises: dfb02fa13954
Create Date: 2026-04-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'e7b3c9d2f1a0'
down_revision: Union[str, None] = 'dfb02fa13954'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('users', 'password')


def downgrade() -> None:
    op.add_column(
        'users',
        sa.Column('password', sa.String(), nullable=True),
    )
