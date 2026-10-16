"""Keep legacy URL identity while allowing an independent R1 observation.

Revision ID: 000014
Revises: 000013
"""

from collections.abc import Sequence

from alembic import op

revision: str = "000014"
down_revision: str | None = "000013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint("uq_articles_track_url", "articles", ["url", "processing_track"])
    op.drop_constraint("articles_url_key", "articles", type_="unique")


def downgrade() -> None:
    raise RuntimeError("Forward-only identity migration; keep legacy and R1 history")
