"""merge 5a37c6bc6cce + 9d1e2f3a4b5c

Revision ID: 43b41105019a
Revises: 5a37c6bc6cce, 9d1e2f3a4b5c
Create Date: 2026-05-14 18:53:33.304054

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '43b41105019a'
down_revision: Union[str, None] = ('5a37c6bc6cce', '9d1e2f3a4b5c')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS is_active boolean DEFAULT true NOT NULL"
    )


def downgrade() -> None:
    pass
