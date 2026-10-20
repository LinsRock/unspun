"""Index current-card retrieval and canonical observation lookups without rewriting data."""

import sqlalchemy as sa
from alembic import op

revision = "000017"
down_revision = "000016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_content_derivations_ready_card",
        "content_derivations",
        ["contract_version", "review_contract", "article_id", "material_id"],
        postgresql_where=sa.text("kind='card' AND status='ready'"),
    )
    op.create_index(
        "ix_articles_canonical_identity",
        "articles",
        [sa.text("coalesce(canonical_content_id, id)")],
    )


def downgrade() -> None:
    op.drop_index("ix_articles_canonical_identity", table_name="articles")
    op.drop_index("ix_content_derivations_ready_card", table_name="content_derivations")
