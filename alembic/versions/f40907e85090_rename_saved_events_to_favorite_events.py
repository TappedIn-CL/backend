"""rename saved_events to favorite_events

Revision ID: f40907e85090
Revises: b2f3c4d5e6f7
Create Date: 2026-05-18 15:47:44.116755

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f40907e85090'
down_revision: Union[str, None] = 'b2f3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "favorite_events",
        new_column_name="favorite_events",
    )


def downgrade() -> None:
    op.alter_column(
        "users",
        "favorite_events",
        new_column_name="favorite_events",
    )