from pgvector.sqlalchemy import Vector
from sqlalchemy import UniqueConstraint, inspect
from sqlalchemy.orm import Session

from unspun.core import models
from unspun.core.db import Base


def test_m1_tables_registered() -> None:
    tables = Base.metadata.tables
    assert {"events", "articles", "fetch_logs", "llm_usage"} <= set(tables)


def test_m2_tables_registered() -> None:
    tables = Base.metadata.tables
    assert {"event_viewpoints", "digests"} <= set(tables)


def test_event_viewpoint_event_id_is_unique() -> None:
    event_id = Base.metadata.tables["event_viewpoints"].c.event_id
    assert event_id.unique
    assert event_id.foreign_keys


def test_digest_unique_on_report_date_and_kind() -> None:
    digests = Base.metadata.tables["digests"]
    uniques = [c for c in digests.constraints if isinstance(c, UniqueConstraint)]
    assert [{col.name for col in c.columns} for c in uniques] == [{"report_date", "kind"}]


def test_article_url_is_unique() -> None:
    url = Base.metadata.tables["articles"].c.url
    assert url.unique


def test_embedding_columns_match_configured_dim() -> None:
    articles = Base.metadata.tables["articles"]
    events = Base.metadata.tables["events"]
    for col in (articles.c.embedding, events.c.centroid):
        assert isinstance(col.type, Vector)
        assert col.type.dim == models.EMBEDDING_DIM


def test_migrated_schema_matches_models(db_session: Session) -> None:
    """Catch drift between hand-written migrations and the ORM models.

    Compares column names and nullability of every model table against the
    migrated database (CI runs `alembic upgrade head` before pytest).
    """
    bind = db_session.get_bind()
    inspector = inspect(bind)
    for table in Base.metadata.tables.values():
        db_cols = {c["name"]: c for c in inspector.get_columns(table.name)}
        assert set(db_cols) == {c.name for c in table.columns}, table.name
        for col in table.columns:
            assert db_cols[col.name]["nullable"] == col.nullable, f"{table.name}.{col.name}"


def test_summary_grounding_is_nullable_jsonb() -> None:
    from sqlalchemy.dialects.postgresql import JSONB

    column = Base.metadata.tables["articles"].c.get("summary_grounding")
    assert column is not None
    assert column.nullable
    assert isinstance(column.type, JSONB)


def test_summary_grounding_migration_is_additive() -> None:
    from io import StringIO

    from alembic import command
    from alembic.config import Config

    output = StringIO()
    config = Config("alembic.ini", stdout=output)
    config.set_main_option("path_separator", "os")
    config.output_buffer = output
    command.upgrade(config, "000006:000007", sql=True)
    sql = output.getvalue()
    assert "ADD COLUMN summary_grounding JSONB" in sql
    assert "NOT NULL" not in sql
    assert "UPDATE articles" not in sql
    assert "DROP" not in sql
