"""Persist single-user feed preferences."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000010"
down_revision: str | None = "000009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feed_preferences",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("sort", sa.Text(), nullable=False),
        sa.Column("range", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_feed_preferences_singleton"),
        sa.CheckConstraint("version > 0", name="ck_feed_preferences_version"),
        sa.CheckConstraint("sort IN ('newest','hot','important')", name="ck_feed_preferences_sort"),
        sa.CheckConstraint("range IN ('today','24h','7d','all')", name="ck_feed_preferences_range"),
    )


def downgrade() -> None:
    op.drop_table("feed_preferences")
