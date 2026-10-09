"""Live event stream endpoint: scored events with time-decayed ordering."""

import math
from collections.abc import Generator
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import Float, func, select
from sqlalchemy.orm import Session, selectinload

from unspun.core.db import session_scope
from unspun.core.models import Event
from unspun.core.params import get_scoring_params
from unspun.core.sources import load_sources

router = APIRouter()

LN2 = math.log(2.0)


def get_db() -> Generator[Session]:
    with session_scope() as session:
        yield session


class ArticleOut(BaseModel):
    id: int
    title: str
    title_zh: str | None
    url: str
    source_id: str
    source_name: str
    published_at: datetime | None


class EventOut(BaseModel):
    id: int
    title: str | None
    summary_zh: str | None
    score_final: float | None
    score_decayed: float | None
    score_breakdown: dict[str, Any] | None
    first_seen_at: datetime
    changed_at: datetime
    articles: list[ArticleOut]


class EventsResponse(BaseModel):
    events: list[EventOut]


@router.get("/api/events", response_model=EventsResponse)
def list_events(
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db),  # noqa: B008
) -> EventsResponse:
    half_life = get_scoring_params().stream.half_life_hours
    age_hours = func.cast(func.extract("epoch", func.now() - Event.changed_at), Float) / 3600.0
    decayed = Event.score_final * func.exp(-LN2 * age_hours / half_life)
    rows = session.execute(
        select(Event, decayed.label("decayed"))
        .options(selectinload(Event.articles))
        .order_by(func.coalesce(decayed, -1.0).desc(), Event.changed_at.desc())
        .limit(limit)
    ).all()
    source_names = {s.id: s.name for s in load_sources()}
    events: list[EventOut] = []
    for event, decayed_score in rows:
        events.append(
            EventOut(
                id=event.id,
                title=event.title,
                summary_zh=event.summary_zh,
                score_final=event.score_final,
                score_decayed=float(decayed_score) if decayed_score is not None else None,
                score_breakdown=event.score_breakdown,
                first_seen_at=event.first_seen_at,
                changed_at=event.changed_at,
                articles=[
                    ArticleOut(
                        id=a.id,
                        title=a.title,
                        title_zh=a.title_zh,
                        url=a.url,
                        source_id=a.source_id,
                        source_name=source_names.get(a.source_id, a.source_id),
                        published_at=a.published_at,
                    )
                    for a in event.articles
                ],
            )
        )
    return EventsResponse(events=events)
