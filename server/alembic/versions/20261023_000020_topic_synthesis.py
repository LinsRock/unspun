"""add retained topic synthesis and semantic audit records

Revision ID: 000020
Revises: 000019
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "000020"
down_revision: str | None = "000019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "topic_syntheses",
        sa.Column("input_fingerprint", sa.Text(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("pipeline_tasks.id"), nullable=False),
        sa.Column("topic_id", sa.Text(), sa.ForeignKey("topics.id"), nullable=False),
        sa.Column("input_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("draft", postgresql.JSONB(), nullable=False),
        sa.Column("generation_receipt", postgresql.JSONB(), nullable=False),
        sa.Column("review", postgresql.JSONB()),
        sa.Column("review_receipt", postgresql.JSONB()),
        sa.Column("response_mode", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("applied", postgresql.JSONB()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('draft','abstained','rejected','stale','applied')",
            name="ck_topic_synthesis_status",
        ),
        sa.CheckConstraint("response_mode IN ('live','mock')", name="ck_topic_synthesis_mode"),
        sa.UniqueConstraint("task_id"),
    )
    op.create_index("ix_topic_syntheses_topic_id", "topic_syntheses", ["topic_id"])


def downgrade() -> None:
    raise RuntimeError(
        "Retain synthesis evidence; use a schema-compatible image or separate restore"
    )
