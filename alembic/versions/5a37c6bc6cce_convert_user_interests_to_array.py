"""convert user interests to array

Revision ID: 5a37c6bc6cce
Revises: 8df045783e25
Create Date: 2026-05-06 14:30:39.008947

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '5a37c6bc6cce'
down_revision: Union[str, None] = '8df045783e25'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "interests",
        existing_type=sa.String(),
        type_=postgresql.ARRAY(sa.String()),
        postgresql_using="ARRAY[interests]",
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "users",
        "interests",
        existing_type=postgresql.ARRAY(sa.String()),
        type_=sa.String(),
        postgresql_using="array_to_string(interests, ',')",
        nullable=True,
    )
