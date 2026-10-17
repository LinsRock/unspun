"""Add independent R1 interests, feedback and browse preferences.

Revision ID: 000015
Revises: 000014
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "000015"
down_revision = "000014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reader_state",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sort", sa.Text(), nullable=False, server_default="recommended"),
        sa.Column("last_mutation_id", sa.Text()),
        sa.Column("last_mutation_fingerprint", sa.Text()),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("id = 1", name="ck_reader_singleton"),
        sa.CheckConstraint("version >= 0", name="ck_reader_version"),
        sa.CheckConstraint("sort IN ('recommended','latest')", name="ck_reader_sort"),
    )
    op.create_table(
        "reader_interests",
        sa.Column("resource_key", sa.Text(), primary_key=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("target", postgresql.JSONB(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("kind IN ('domain','term','source','author')", name="ck_interest_kind"),
    )
    op.create_table(
        "content_feedback",
        sa.Column("article_id", sa.Integer(), sa.ForeignKey("articles.id"), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "value IN ('interested','not_interested')", name="ck_content_feedback_value"
        ),
    )
    op.create_table(
        "reader_changes",
        sa.Column("version", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("mutation_id", sa.Text(), nullable=False, unique=True),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("target", postgresql.JSONB(), nullable=False),
        sa.Column("value", postgresql.JSONB()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    raise RuntimeError("R1 reader data is retained; disable routes instead of deleting preferences")
