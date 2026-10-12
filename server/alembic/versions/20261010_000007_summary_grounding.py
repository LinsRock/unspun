"""add nullable original evidence metadata to article summaries

Revision ID: 000007
Revises: 000006
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "000007"
down_revision: str | None = "000006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("articles", sa.Column("summary_grounding", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("articles", "summary_grounding")
