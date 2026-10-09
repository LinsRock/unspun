import math
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from unspun.core.models import EMBEDDING_DIM, Article, Event, LlmUsage
from unspun.pipeline.cluster import assign_article
from unspun.pipeline.summarize import embed_articles, summarize_article

THRESHOLD = 0.72


class FakeLlm:
    def chat_json(
        self,
        session: Session,
        *,
        model: str,
        system: str,
        user: str,
        purpose: str,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        session.add(LlmUsage(purpose=purpose, model=model, prompt_tokens=10, cost_usd=0.001))
        return {"title_zh": "zh-title", "summary_zh": "zh-summary"}

    def embed(self, session: Session, texts: list[str]) -> list[list[float]]:
        return [unit_vector(i) for i in range(len(texts))]


def unit_vector(axis: int, dim: int = EMBEDDING_DIM) -> list[float]:
    v = [0.0] * dim
    v[axis] = 1.0
    return v


def near_vector(axis: int, other_axis: int, cosine: float) -> list[float]:
    v = [0.0] * EMBEDDING_DIM
    v[axis] = cosine
    v[other_axis] = math.sqrt(1.0 - cosine * cosine)
    return v


def make_article(n: int, **extra: Any) -> Article:
    return Article(source_id="sample", url=f"https://example.com/{n}", title=f"story {n}", **extra)


def test_summarize_article_sets_fields_and_records_usage(db_session: Session) -> None:
    article = make_article(1, content="body text")
    db_session.add(article)
    summarize_article(db_session, FakeLlm(), article)
    assert article.summary_zh == "zh-summary"
    assert article.title_zh == "zh-title"
    usage = db_session.scalars(select(LlmUsage)).one()
    assert usage.purpose == "summary"


def test_embed_articles_assigns_vectors(db_session: Session) -> None:
    articles = [make_article(n, summary_zh="s", title_zh="t") for n in range(3)]
    db_session.add_all(articles)
    embed_articles(db_session, FakeLlm(), articles)
    assert all(a.embedding is not None for a in articles)


def test_assign_article_groups_similar_and_splits_distant(db_session: Session) -> None:
    a1 = make_article(1, summary_zh="s", title_zh="t", embedding=unit_vector(0))
    a2 = make_article(2, summary_zh="s", title_zh="t", embedding=near_vector(0, 1, 0.9))
    a3 = make_article(3, summary_zh="s", title_zh="t", embedding=unit_vector(5))
    db_session.add_all([a1, a2, a3])

    assert assign_article(db_session, a1, THRESHOLD) is True
    assert assign_article(db_session, a2, THRESHOLD) is False
    assert assign_article(db_session, a3, THRESHOLD) is True

    events = list(db_session.scalars(select(Event)))
    assert len(events) == 2
    assert a1.event_id == a2.event_id
    assert a3.event_id != a1.event_id
    # Centroid moved to the mean of both members and stays unit-length.
    assert a1.event is not None
    centroid = [float(x) for x in cast(list[Any], a1.event.centroid)]
    norm = math.sqrt(sum(x * x for x in centroid))
    assert math.isclose(norm, 1.0, rel_tol=1e-6)
    assert 0.9 < centroid[0] < 1.0
