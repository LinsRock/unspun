"""Persist single-user reading state and feed preferences."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000010"
down_revision: str | None = "000009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "event_read_states",
        sa.Column(
            "event_id",
            sa.Integer(),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("is_read", sa.Boolean(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_event_read_version"),
        sa.CheckConstraint("is_read = (read_at IS NOT NULL)", name="ck_event_read_timestamp"),
    )
    op.create_table(
        "feed_preferences",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("sort", sa.Text(), nullable=False),
        sa.Column("range", sa.Text(), nullable=False),
        sa.Column("unread_only", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_feed_preferences_singleton"),
        sa.CheckConstraint("version > 0", name="ck_feed_preferences_version"),
        sa.CheckConstraint("sort IN ('newest','hot','important')", name="ck_feed_preferences_sort"),
        sa.CheckConstraint("range IN ('today','24h','7d','all')", name="ck_feed_preferences_range"),
    )


def downgrade() -> None:
    op.drop_table("feed_preferences")
    op.drop_table("event_read_states")
