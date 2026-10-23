"""retain typed topic preferences and all successful reader request receipts

Revision ID: 000021
Revises: 000020
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000021"
down_revision: str | None = "000020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reader_requests",
        sa.Column("mutation_id", sa.Text(), primary_key=True),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("unchanged", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("version >= 0", name="ck_reader_request_version"),
    )
    op.create_table(
        "topic_preferences",
        sa.Column("topic_id", sa.Text(), sa.ForeignKey("topics.id"), primary_key=True),
        sa.Column("followed", sa.Boolean(), nullable=False),
        sa.Column("feedback", sa.Text()),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "feedback IN ('interested','not_interested')", name="ck_topic_preference_feedback"
        ),
        sa.CheckConstraint("followed OR feedback IS NOT NULL", name="ck_topic_preference_active"),
        sa.CheckConstraint("version > 0", name="ck_topic_preference_version"),
    )


def downgrade() -> None:
    raise RuntimeError("Retain reader history; use a schema-compatible image or separate restore")
