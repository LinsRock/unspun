"""Incremental event clustering: nearest-centroid assignment by cosine similarity."""

from datetime import UTC, datetime

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from unspun.core.db import session_scope
from unspun.core.logging import get_logger
from unspun.core.models import Article, Event
from unspun.core.params import get_scoring_params

log = get_logger("unspun.pipeline.cluster")

CLUSTER_BATCH_LIMIT = 500


def assign_article(session: Session, article: Article, threshold: float) -> bool:
    """Attach the article to the nearest event or start a new one.

    Returns True when a new event was created.
    """
    dist = Event.centroid.cosine_distance(article.embedding)
    row = session.execute(
        select(Event, dist.label("dist")).where(Event.centroid.is_not(None)).order_by(dist).limit(1)
    ).first()
    if row is not None and (1.0 - float(row[1])) >= threshold:
        event: Event = row[0]
        article.event = event
        _refresh_centroid(session, event)
        event.changed_at = datetime.now(UTC)
        return False
    event = Event(
        title=article.title_zh or article.title,
        summary_zh=article.summary_zh,
        centroid=article.embedding,
    )
    session.add(event)
    article.event = event
    return True


def _refresh_centroid(session: Session, event: Event) -> None:
    # Autoflush makes this query see the article just attached.
    embeddings = list(
        session.scalars(
            select(Article.embedding).where(
                Article.event_id == event.id, Article.embedding.is_not(None)
            )
        )
    )
    if not embeddings:
        return
    stacked = np.asarray([np.asarray(e, dtype=np.float64) for e in embeddings])
    centroid = stacked.mean(axis=0)
    norm = float(np.linalg.norm(centroid))
    if norm > 0:
        centroid = centroid / norm
    event.centroid = centroid.tolist()


def cluster_pending(limit: int = CLUSTER_BATCH_LIMIT) -> tuple[int, int]:
    """Assign all summarized+embedded articles to events; returns (assigned, created)."""
    threshold = get_scoring_params().clustering.similarity_threshold
    with session_scope() as session:
        ids = list(
            session.scalars(
                select(Article.id)
                .where(Article.embedding.is_not(None), Article.event_id.is_(None))
                .order_by(Article.id)
                .limit(limit)
            )
        )
    assigned = 0
    created = 0
    for article_id in ids:
        try:
            with session_scope() as session:
                article = session.get(Article, article_id)
                if article is None or article.event_id is not None:
                    continue
                if assign_article(session, article, threshold):
                    created += 1
                assigned += 1
        except Exception:
            log.exception("cluster_assign_failed", article_id=article_id)
    return assigned, created
