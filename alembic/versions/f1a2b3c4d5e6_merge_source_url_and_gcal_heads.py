"""merge source_url and gcal/going_to heads (no-op)

Revision ID: f1a2b3c4d5e6
Revises: e0f1a2b3c4d5, b7fa6abf03e4
Create Date: 2026-06-02 19:00:00.000000

Run after both parent branches are satisfied. If your DB is already at
c1d2e3f4a5b6 with gcal/going_to schema applied, use:

  alembic upgrade e0f1a2b3c4d5
  alembic stamp b7fa6abf03e4
  alembic upgrade f1a2b3c4d5e6

Or stamp f1a2b3c4d5e6 directly if both branches are already reflected in schema.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, tuple[str, ...], None] = ("e0f1a2b3c4d5", "b7fa6abf03e4")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
