from pgvector.sqlalchemy import Vector

from unspun.core import models
from unspun.core.db import Base


def test_m1_tables_registered() -> None:
    tables = Base.metadata.tables
    assert {"events", "articles", "fetch_logs", "llm_usage"} <= set(tables)


def test_article_url_is_unique() -> None:
    url = Base.metadata.tables["articles"].c.url
    assert url.unique


def test_embedding_columns_match_configured_dim() -> None:
    articles = Base.metadata.tables["articles"]
    events = Base.metadata.tables["events"]
    for col in (articles.c.embedding, events.c.centroid):
        assert isinstance(col.type, Vector)
        assert col.type.dim == models.EMBEDDING_DIM
