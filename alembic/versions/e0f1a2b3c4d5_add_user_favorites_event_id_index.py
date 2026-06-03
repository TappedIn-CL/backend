"""add user_favorites event_id index

Revision ID: e0f1a2b3c4d5
Revises: c1d2e3f4a5b6
Create Date: 2026-06-02 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "e0f1a2b3c4d5"
down_revision: Union[str, None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_user_favorites_event_id",
        "user_favorites",
        ["event_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_user_favorites_event_id", table_name="user_favorites")
