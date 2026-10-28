"""Incremental event clustering: nearest-centroid assignment by cosine similarity."""

from datetime import UTC, datetime

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from unspun.core.content import legacy_event_condition, require_legacy
from unspun.core.models import Article, Event
from unspun.core.reading import refresh_event_text


def assign_article(session: Session, article: Article, threshold: float) -> bool:
    """Attach the article to the nearest event or start a new one.

    Returns True when a new event was created.
    """
    require_legacy(article)
    dist = Event.centroid.cosine_distance(article.embedding)
    row = session.execute(
        select(Event, dist.label("dist"))
        .where(Event.centroid.is_not(None), legacy_event_condition())
        .order_by(dist)
        .limit(1)
    ).first()
    if row is not None and (1.0 - float(row[1])) >= threshold:
        event: Event = row[0]
        article.event = event
        refresh_centroid(session, event)
        refresh_event_text(event)
        event.changed_at = datetime.now(UTC)
        return False
    event = Event(
        title=article.title_zh or article.title,
        summary_zh=article.summary_zh,
        centroid=article.embedding,
    )
    session.add(event)
    article.event = event
    session.flush()
    refresh_event_text(event)
    return True


def refresh_centroid(session: Session, event: Event) -> None:
    # Autoflush makes this query see the article just attached.
    embeddings = list(
        session.scalars(
            select(Article.embedding).where(
                Article.event_id == event.id,
                Article.embedding.is_not(None),
                Article.processing_track == "legacy",
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
