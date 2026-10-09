"""add pipeline_runs

Revision ID: 000005
Revises: 000004
Create Date: 2026-10-09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000005"
down_revision: str | None = "000004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("summarized", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("embedded", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("clustered", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("new_events", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("scored", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_pipeline_runs_run_at", "pipeline_runs", ["run_at"])


def downgrade() -> None:
    op.drop_table("pipeline_runs")
