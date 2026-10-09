"""add articles.title_zh

Revision ID: 000003
Revises: 000002
Create Date: 2026-10-09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000003"
down_revision: str | None = "000002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("articles", sa.Column("title_zh", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("articles", "title_zh")
