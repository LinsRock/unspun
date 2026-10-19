"""Durable R2 scan and processing selection receipts, without historical backfill."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "000016"
down_revision = "000015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discovery_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("cycle_key", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quotas", postgresql.JSONB(), nullable=False),
        sa.Column("counters", postgresql.JSONB(), nullable=False),
        sa.Column("material_tasks", postgresql.JSONB(), nullable=False),
        sa.Column("paid_outcomes", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("source_id", "cycle_key", name="uq_discovery_batch"),
    )
    op.create_index("ix_discovery_batches_source_id", "discovery_batches", ["source_id"])


def downgrade() -> None:
    raise RuntimeError("R2 discovery receipts are retained; roll application code back instead")
