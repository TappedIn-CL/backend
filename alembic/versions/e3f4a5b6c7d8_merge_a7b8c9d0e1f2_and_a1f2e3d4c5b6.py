"""merge a7b8c9d0e1f2 and a1f2e3d4c5b6

Revision ID: e3f4a5b6c7d8
Revises: a7b8c9d0e1f2, a1f2e3d4c5b6
Create Date: 2026-05-27 00:00:00.000000

"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = 'e3f4a5b6c7d8'
down_revision: Union[str, None] = ('a7b8c9d0e1f2', 'a1f2e3d4c5b6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass