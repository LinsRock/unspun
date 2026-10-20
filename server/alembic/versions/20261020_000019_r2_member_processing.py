"""add versioned vectors and member judgments

Revision ID: 000019
Revises: 000018
Create Date: 2026-10-20 17:20:29.441035

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "000019"
down_revision: str | None = "000018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "content_vectors",
        sa.Column("input_fingerprint", sa.Text(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("material_id", sa.Integer(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("contract_version", sa.Text(), nullable=False),
        sa.Column("input_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("vector", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("call_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "jsonb_typeof(vector)='array' AND jsonb_array_length(vector)=dimensions",
            name="ck_content_vector_size",
        ),
        sa.CheckConstraint("dimensions > 0", name="ck_content_vector_dimensions"),
        sa.ForeignKeyConstraint(
            ["article_id", "material_id"],
            ["content_materials.article_id", "content_materials.id"],
        ),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["articles.id"],
        ),
        sa.PrimaryKeyConstraint("input_fingerprint"),
    )
    op.create_index(
        op.f("ix_content_vectors_article_id"), "content_vectors", ["article_id"], unique=False
    )
    op.create_table(
        "member_judgments",
        sa.Column("input_fingerprint", sa.Text(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("topic_id", sa.Text(), nullable=False),
        sa.Column("topic_revision", sa.Integer(), nullable=False),
        sa.Column("input_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("decision", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("review", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("applied_revision", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('draft','independent','rejected','stale','applied')",
            name="ck_member_judgment_status",
        ),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["articles.id"],
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["pipeline_tasks.id"],
        ),
        sa.ForeignKeyConstraint(
            ["topic_id"],
            ["topics.id"],
        ),
        sa.PrimaryKeyConstraint("input_fingerprint"),
    )
    op.create_index(
        op.f("ix_member_judgments_article_id"), "member_judgments", ["article_id"], unique=False
    )
    op.create_index(
        op.f("ix_member_judgments_topic_id"), "member_judgments", ["topic_id"], unique=False
    )


def downgrade() -> None:
    raise RuntimeError(
        "Member decisions and vectors must be retained; use a schema-compatible image "
        "or restore into a separate database"
    )
