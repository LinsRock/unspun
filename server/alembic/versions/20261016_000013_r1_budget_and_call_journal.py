"""r1 shared budget and independent call journal

Revision ID: 000013
Revises: 000012
Create Date: 2026-10-16 15:07:08.971715

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "000013"
down_revision: str | None = "000012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "budget_carry",
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("amount_usd", sa.Numeric(precision=24, scale=12), nullable=False),
        sa.Column("provider_monthly_usd", sa.Numeric(precision=24, scale=12), nullable=True),
        sa.Column("ledger_at_observation_usd", sa.Numeric(precision=24, scale=12), nullable=False),
        sa.Column("basis", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount_usd >= 0", name="ck_budget_carry_amount"),
        sa.PrimaryKeyConstraint("month"),
    )
    op.create_table(
        "budget_policy",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("monthly_limit_usd", sa.Numeric(precision=24, scale=12), nullable=False),
        sa.Column("stage_caps", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("coverage_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("incident", sa.Text(), nullable=True),
        sa.Column("provider_limit_usd", sa.Numeric(precision=24, scale=12), nullable=True),
        sa.Column("provider_usage_usd", sa.Numeric(precision=24, scale=12), nullable=True),
        sa.Column("provider_limit_kind", sa.Text(), nullable=True),
        sa.Column("key_fingerprint", sa.Text(), nullable=True),
        sa.Column("provider_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("scope IN ('production','evaluation')", name="ck_budget_scope"),
        sa.CheckConstraint("id = 1", name="ck_budget_singleton"),
        sa.CheckConstraint("monthly_limit_usd BETWEEN 0 AND 50", name="ck_budget_limit"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "billed_requests",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("logical_key", sa.Text(), nullable=True),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("phase", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("request_fingerprint", sa.Text(), nullable=False),
        sa.Column("price_version", sa.Text(), nullable=False),
        sa.Column("reserved_usd", sa.Numeric(precision=24, scale=12), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("task_attempt_id", sa.Integer(), nullable=True),
        sa.Column("article_id", sa.Integer(), nullable=True),
        sa.Column("source_id", sa.Text(), nullable=True),
        sa.Column("object_key", sa.Text(), nullable=True),
        sa.Column("usage_id", sa.Integer(), nullable=True),
        sa.Column("provider_generation_id", sa.Text(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("response_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("usage_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("reconciliation", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('reserved','usage_unknown','responded','settled_without_result')",
            name="ck_billed_request_status",
        ),
        sa.CheckConstraint("reserved_usd >= 0", name="ck_billed_request_reserved"),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["articles.id"],
        ),
        sa.ForeignKeyConstraint(
            ["task_attempt_id"],
            ["task_attempts.id"],
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["pipeline_tasks.id"],
        ),
        sa.ForeignKeyConstraint(
            ["usage_id"],
            ["llm_usage.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("logical_key"),
        sa.UniqueConstraint("usage_id"),
    )
    op.create_index(
        op.f("ix_billed_requests_article_id"), "billed_requests", ["article_id"], unique=False
    )
    op.create_index(
        "ix_billed_requests_object", "billed_requests", ["object_key", "status"], unique=False
    )
    op.create_index("ix_billed_requests_started", "billed_requests", ["started_at"], unique=False)
    op.create_index("ix_billed_requests_status", "billed_requests", ["status"], unique=False)
    op.alter_column(
        "llm_usage",
        "prompt_tokens",
        existing_type=sa.INTEGER(),
        nullable=True,
        existing_server_default=sa.text("0"),
    )
    op.alter_column(
        "llm_usage",
        "completion_tokens",
        existing_type=sa.INTEGER(),
        nullable=True,
        existing_server_default=sa.text("0"),
    )


def downgrade() -> None:
    raise RuntimeError("Forward-only accounting migration; use a compatible rollback image")
