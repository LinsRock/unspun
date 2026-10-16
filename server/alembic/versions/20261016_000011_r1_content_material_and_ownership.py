"""r1 content material and ownership

Revision ID: 000011
Revises: 000010
Create Date: 2026-10-16 13:48:37.721842

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "000011"
down_revision: str | None = "000010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "content_identities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("namespace", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["articles.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("namespace", "external_id", name="uq_content_identity"),
    )
    op.create_index(
        op.f("ix_content_identities_article_id"), "content_identities", ["article_id"], unique=False
    )
    op.create_table(
        "content_materials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("input_fingerprint", sa.Text(), nullable=False),
        sa.Column("text_fingerprint", sa.Text(), nullable=True),
        sa.Column("metadata_fingerprint", sa.Text(), nullable=False),
        sa.Column("extractor_version", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("access_status", sa.Text(), nullable=False),
        sa.Column("completeness", sa.Text(), nullable=False),
        sa.Column("completeness_basis", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_fingerprint", sa.Text(), nullable=True),
        sa.Column("paragraphs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_excerpt", sa.Text(), nullable=True),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "access_status IN ('ok','restricted','unavailable','failed')", name="ck_material_access"
        ),
        sa.CheckConstraint(
            "completeness IN ('observed_unit','partial','none','unknown')",
            name="ck_material_completeness",
        ),
        sa.CheckConstraint("jsonb_typeof(paragraphs) = 'array'", name="ck_material_paragraphs"),
        sa.CheckConstraint(
            "scope IN ('open_text_unit','editorial_edition','complete_brief','preview',"
            "'question_background','media_description','feed_lead','none')",
            name="ck_material_scope",
        ),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["articles.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("article_id", "id", name="uq_content_material_owner"),
        sa.UniqueConstraint("article_id", "input_fingerprint", name="uq_content_material_input"),
    )
    op.create_index(
        op.f("ix_content_materials_article_id"), "content_materials", ["article_id"], unique=False
    )
    op.create_index(
        op.f("ix_content_materials_text_fingerprint"),
        "content_materials",
        ["text_fingerprint"],
        unique=False,
    )
    op.create_table(
        "content_observations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("item_key", sa.Text(), nullable=False),
        sa.Column("discovered_url", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observation_fingerprint", sa.Text(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("signals", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("metadata_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint("rank IS NULL OR rank > 0", name="ck_content_observation_rank"),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["articles.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id", "item_key", "observation_fingerprint", name="uq_content_observation"
        ),
    )
    op.create_index(
        op.f("ix_content_observations_article_id"),
        "content_observations",
        ["article_id"],
        unique=False,
    )
    op.create_index(
        "ix_content_observations_source_time",
        "content_observations",
        ["source_id", "observed_at"],
        unique=False,
    )
    op.create_table(
        "content_urls",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("relation", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["articles.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("url"),
    )
    op.create_index(
        op.f("ix_content_urls_article_id"), "content_urls", ["article_id"], unique=False
    )
    op.create_table(
        "content_derivations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("material_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("input_fingerprint", sa.Text(), nullable=False),
        sa.Column("metadata_fingerprint", sa.Text(), nullable=False),
        sa.Column("contract_version", sa.Text(), nullable=False),
        sa.Column("generation_model", sa.Text(), nullable=True),
        sa.Column("review_contract", sa.Text(), nullable=False),
        sa.Column("review_model", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("review_evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
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
        sa.CheckConstraint(
            "kind IN ('features','admission','card','guide')", name="ck_derivation_kind"
        ),
        sa.CheckConstraint(
            "status != 'ready' OR (payload IS NOT NULL AND jsonb_typeof(payload)='object' "
            "AND review_evidence IS NOT NULL AND jsonb_typeof(review_evidence)='object')",
            name="ck_derivation_ready_evidence",
        ),
        sa.CheckConstraint(
            "status IN ('pending','generating','review_pending','budget_deferred',"
            "'ready','rejected','failed','invalidated')",
            name="ck_derivation_status",
        ),
        sa.ForeignKeyConstraint(
            ["article_id", "material_id"],
            ["content_materials.article_id", "content_materials.id"],
            name="fk_content_derivation_material",
        ),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["articles.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "article_id", "kind", "input_fingerprint", name="uq_content_derivation_input"
        ),
    )
    op.create_index(
        "ix_content_derivations_article_kind",
        "content_derivations",
        ["article_id", "kind"],
        unique=False,
    )
    op.add_column(
        "articles",
        sa.Column("processing_track", sa.Text(), server_default="legacy", nullable=False),
    )
    op.add_column(
        "articles", sa.Column("content_form", sa.Text(), server_default="unknown", nullable=False)
    )
    op.add_column("articles", sa.Column("genre", sa.Text(), nullable=True))
    op.add_column("articles", sa.Column("platform", sa.Text(), nullable=True))
    op.add_column("articles", sa.Column("publisher_name", sa.Text(), nullable=True))
    op.add_column(
        "articles", sa.Column("r1_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.add_column("articles", sa.Column("metadata_fingerprint", sa.Text(), nullable=True))
    op.add_column("articles", sa.Column("canonical_content_id", sa.Integer(), nullable=True))
    op.add_column("articles", sa.Column("current_material_id", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_articles_track", "articles", "processing_track IN ('legacy','r1')"
    )
    op.create_check_constraint(
        "ck_articles_form",
        "articles",
        "content_form IN ('unknown','article','post','question','video','audio')",
    )
    op.create_check_constraint(
        "ck_articles_canonical_not_self",
        "articles",
        "canonical_content_id IS NULL OR canonical_content_id != id",
    )
    op.create_index("ix_articles_track", "articles", ["processing_track"], unique=False)
    op.create_foreign_key(
        "fk_articles_current_material",
        "articles",
        "content_materials",
        ["id", "current_material_id"],
        ["article_id", "id"],
        use_alter=True,
    )
    op.create_foreign_key(
        "fk_articles_canonical", "articles", "articles", ["canonical_content_id"], ["id"]
    )


def downgrade() -> None:
    raise RuntimeError(
        "R1 migrations preserve data; roll back application/config without downgrade"
    )
