"""add retained topic foundation

Revision ID: 000018
Revises: 000017
Create Date: 2026-10-20 16:05:32.446296

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "000018"
down_revision: str | None = "000017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "topics",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("domains", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("definition_revision", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("jsonb_typeof(domains)='array'", name="ck_topic_domains"),
        sa.CheckConstraint("kind IN ('event','issue')", name="ck_topic_kind"),
        sa.CheckConstraint("status IN ('active','archived')", name="ck_topic_status"),
        sa.CheckConstraint("revision >= 0", name="ck_topic_revision"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "topic_changes",
        sa.Column("topic_id", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("mutation_id", sa.Text(), nullable=False),
        sa.Column("request_fingerprint", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("command", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("revision > 0", name="ck_topic_change_revision"),
        sa.ForeignKeyConstraint(
            ["topic_id"],
            ["topics.id"],
        ),
        sa.PrimaryKeyConstraint("topic_id", "revision"),
        sa.UniqueConstraint("topic_id", "mutation_id", name="uq_topic_mutation"),
    )
    op.create_table(
        "topic_derivations",
        sa.Column("topic_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("supersedes_revision", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), server_default="draft", nullable=False),
        sa.Column("input_fingerprint", sa.Text(), nullable=False),
        sa.Column("input_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("contract", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("kind IN ('overview','guide')", name="ck_topic_derivation_kind"),
        sa.CheckConstraint("status='draft'", name="ck_topic_derivation_draft"),
        sa.CheckConstraint(
            "supersedes_revision IS NULL OR supersedes_revision < revision",
            name="ck_topic_derivation_predecessor",
        ),
        sa.ForeignKeyConstraint(
            ["topic_id", "kind", "supersedes_revision"],
            ["topic_derivations.topic_id", "topic_derivations.kind", "topic_derivations.revision"],
        ),
        sa.ForeignKeyConstraint(
            ["topic_id", "revision"],
            ["topic_changes.topic_id", "topic_changes.revision"],
        ),
        sa.ForeignKeyConstraint(
            ["topic_id"],
            ["topics.id"],
        ),
        sa.PrimaryKeyConstraint("topic_id", "kind", "revision"),
    )
    op.create_table(
        "topic_updates",
        sa.Column("topic_id", sa.Text(), nullable=False),
        sa.Column("update_id", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("supersedes_revision", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("input_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("input_fingerprint", sa.Text(), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("status IN ('active','retracted')", name="ck_topic_update_status"),
        sa.CheckConstraint(
            "supersedes_revision IS NULL OR supersedes_revision < revision",
            name="ck_topic_update_predecessor",
        ),
        sa.ForeignKeyConstraint(
            ["topic_id", "revision"],
            ["topic_changes.topic_id", "topic_changes.revision"],
        ),
        sa.ForeignKeyConstraint(
            ["topic_id", "update_id", "supersedes_revision"],
            ["topic_updates.topic_id", "topic_updates.update_id", "topic_updates.revision"],
        ),
        sa.ForeignKeyConstraint(
            ["topic_id"],
            ["topics.id"],
        ),
        sa.PrimaryKeyConstraint("topic_id", "update_id", "revision"),
    )
    op.create_table(
        "topic_members",
        sa.Column("topic_id", sa.Text(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("material_id", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("relation", sa.Text(), nullable=False),
        sa.Column("basis", sa.Text(), nullable=False),
        sa.Column("decision_version", sa.Text(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("input_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint("jsonb_typeof(evidence)='array'", name="ck_topic_member_evidence"),
        sa.CheckConstraint(
            "relation IN ('report','background','opinion','explanation','reprint')",
            name="ck_topic_member_relation",
        ),
        sa.ForeignKeyConstraint(
            ["article_id", "material_id"],
            ["content_materials.article_id", "content_materials.id"],
        ),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["articles.id"],
        ),
        sa.ForeignKeyConstraint(
            ["topic_id", "revision"],
            ["topic_changes.topic_id", "topic_changes.revision"],
        ),
        sa.ForeignKeyConstraint(
            ["topic_id"],
            ["topics.id"],
        ),
        sa.PrimaryKeyConstraint("topic_id", "article_id"),
    )


def downgrade() -> None:
    raise RuntimeError(
        "Topic history must be retained; use a schema-compatible image "
        "or restore into a separate database"
    )
