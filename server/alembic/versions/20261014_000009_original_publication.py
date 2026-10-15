"""Store original publication provenance without inventing legacy timestamps."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "000009"
down_revision: str | None = "000008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("events", sa.Column("public_impact", JSONB(), nullable=True))
    for name, type_ in [
        ("reported_at", sa.DateTime(timezone=True)),
        ("reported_date", sa.Date()),
        ("reported_basis", sa.Text()),
        ("publisher_group", sa.Text()),
    ]:
        op.add_column("articles", sa.Column(name, type_, nullable=True))
    op.add_column(
        "articles",
        sa.Column("reported_precision", sa.Text(), nullable=False, server_default="unknown"),
    )
    op.add_column(
        "articles", sa.Column("content_basis", sa.Text(), nullable=False, server_default="unknown")
    )
    op.create_index(
        "ix_articles_event_publication", "articles", ["event_id", "reported_at", "fetched_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_articles_event_publication", table_name="articles")
    for name in [
        "reported_at",
        "reported_date",
        "reported_precision",
        "reported_basis",
        "publisher_group",
        "content_basis",
    ]:
        op.drop_column("articles", name)
    op.drop_column("events", "public_impact")
