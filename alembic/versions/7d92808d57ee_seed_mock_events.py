"""seed mock events

Revision ID: 7d92808d57ee
Revises: 727b0c1a8198
Create Date: 2026-04-21 20:10:02.150322

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7d92808d57ee'
down_revision: Union[str, None] = '727b0c1a8198'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO events (id, title, description, date, cost, location, category, created_at)
            VALUES
                ('11111111-1111-1111-1111-111111111111'::uuid, 'Dozy Cafe', 'UCLA matcha pop-up', '2026-04-24 18:30:00+00', 6.5, 'UCLA', 'Food & Drink', '2026-04-20 08:00:00+00'),
                ('22222222-2222-2222-2222-222222222222'::uuid, 'Indie Film Night', 'Community screening and Q&A.', '2026-04-27 19:00:00+00', 8.5, 'Cinema One', 'Arts', '2026-04-20 08:05:00+00'),
                ('33333333-3333-3333-3333-333333333333'::uuid, 'LA fashion pop-up', 'buy tuff fits', '2026-05-01 19:00:00+00', 9.0, 'Westwood', 'Fashion', '2026-04-27 08:05:00+00')
            ON CONFLICT (id) DO NOTHING
            """,
        ),
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DELETE FROM events
            WHERE id IN (
                '11111111-1111-1111-1111-111111111111'::uuid,
                '22222222-2222-2222-2222-222222222222'::uuid,
                '33333333-3333-3333-3333-333333333333'::uuid
            )
            """,
        ),
    )
