"""r1 recoverable stage tasks

Revision ID: 000012
Revises: 000011
Create Date: 2026-10-16 14:10:38.384028

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "000012"
down_revision: str | None = "000011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source_states",
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("owner", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("period_seconds", sa.Integer(), nullable=False),
        sa.Column("schedule_version", sa.Text(), nullable=False),
        sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consecutive_failures", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_new_item_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_item_count", sa.Integer(), nullable=True),
        sa.CheckConstraint("owner IN ('legacy','r1')", name="ck_source_state_owner"),
        sa.CheckConstraint("consecutive_failures >= 0", name="ck_source_state_failures"),
        sa.CheckConstraint("period_seconds >= 60", name="ck_source_state_period"),
        sa.PrimaryKeyConstraint("source_id"),
    )
    op.create_table(
        "pipeline_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("queue", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=True),
        sa.Column("source_id", sa.Text(), nullable=True),
        sa.Column("input_fingerprint", sa.Text(), nullable=False),
        sa.Column("strategy_version", sa.Text(), nullable=False),
        sa.Column("cycle_key", sa.Text(), nullable=True),
        sa.Column("dedupe_key", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failures", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("claim_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_by", sa.Text(), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(status = 'running') = (lease_until IS NOT NULL)", name="ck_task_lease"
        ),
        sa.CheckConstraint(
            "queue IN ('discovery','material','paid','guide','deadline')", name="ck_task_queue"
        ),
        sa.CheckConstraint(
            "status IN ('pending','running','retry_wait','budget_deferred',"
            "'blocked','completed','failed')",
            name="ck_task_status",
        ),
        sa.CheckConstraint("claim_version >= 0", name="ck_task_version"),
        sa.CheckConstraint(
            "max_attempts BETWEEN 1 AND 10 AND attempts >= 0 AND failures BETWEEN 0 "
            "AND max_attempts",
            name="ck_task_attempts",
        ),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["articles.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key"),
    )
    op.create_index(
        op.f("ix_pipeline_tasks_article_id"), "pipeline_tasks", ["article_id"], unique=False
    )
    op.create_index(
        "ix_pipeline_tasks_due",
        "pipeline_tasks",
        ["queue", "status", "due_at", "priority", "id"],
        unique=False,
    )
    op.create_index(
        "ix_pipeline_tasks_lease", "pipeline_tasks", ["status", "lease_until"], unique=False
    )
    op.create_index(
        "uq_pipeline_tasks_active_object",
        "pipeline_tasks",
        ["object_key"],
        unique=True,
        postgresql_where=sa.text("status='running'"),
    )
    op.create_table(
        "task_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("claim_version", sa.Integer(), nullable=False),
        sa.Column("worker", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('running','completed','failed','lease_expired','deferred','blocked')",
            name="ck_attempt_status",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["pipeline_tasks.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "claim_version", name="uq_task_attempt_claim"),
    )
    op.create_index(op.f("ix_task_attempts_task_id"), "task_attempts", ["task_id"], unique=False)


def downgrade() -> None:
    raise RuntimeError("R1 task history is retained; disable consumers instead of dropping data")
