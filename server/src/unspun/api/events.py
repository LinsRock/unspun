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
from unspun.core.logging import get_logger
from unspun.core.models import Event, EventViewpoint
from unspun.core.params import get_scoring_params
from unspun.core.sources import load_sources

router = APIRouter()

log = get_logger("unspun.api.events")

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
    content_quality: str | None = None


class ViewpointClaimOut(BaseModel):
    article_id: int
    claim: str
    evidence_quote: str | None = None


class ViewpointDisagreementOut(BaseModel):
    point: str
    claim_indexes: list[int]
    kind: str | None = None


class ViewpointOut(BaseModel):
    status: str | None = None
    claims: list[ViewpointClaimOut]
    disagreements: list[ViewpointDisagreementOut]
    model: str
    generated_at: datetime


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
    viewpoint: ViewpointOut | None = None


def viewpoint_out(row: EventViewpoint | None, article_ids: set[int]) -> ViewpointOut | None:
    """Serve the stored payload with claims restricted to this event's articles.

    Articles can be reassigned between regenerations, so membership is
    enforced here once for every consumer (M2 acceptance: no claim may point
    at a foreign source); disagreement indexes are remapped to the kept
    claims, mirroring parse_viewpoints_payload.
    """
    if row is None:
        return None
    try:
        parsed = ViewpointOut.model_validate(
            {**row.payload, "model": row.model, "generated_at": row.generated_at}
        )
    except Exception as exc:
        # A payload the current schema cannot read must not take down the
        # whole feed; the event just renders without its comparison. No
        # traceback: the poisoned row would log one per poll until the
        # event's articles next change.
        log.warning("viewpoint_payload_invalid", event_id=row.event_id, error=str(exc))
        return None
    index_map = {
        i: new_i
        for new_i, (i, _) in enumerate(
            (i, c) for i, c in enumerate(parsed.claims) if c.article_id in article_ids
        )
    }
    parsed.claims = [c for i, c in enumerate(parsed.claims) if i in index_map]
    remapped = [
        ViewpointDisagreementOut(point=d.point, claim_indexes=indexes, kind=d.kind)
        for d in parsed.disagreements
        if len(indexes := sorted(index_map[i] for i in d.claim_indexes if i in index_map)) >= 2
    ]
    parsed.disagreements = remapped
    return parsed


class EventsResponse(BaseModel):
    events: list[EventOut]


def event_out(event: Event, decayed_score: float | None, source_names: dict[str, str]) -> EventOut:
    """Serialize a live event or a digest snapshot with the same provenance rules."""
    return EventOut(
        id=event.id,
        title=event.title,
        summary_zh=event.summary_zh,
        score_final=event.score_final,
        score_decayed=decayed_score,
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
                content_quality=(
                    a.summary_grounding.get("status")
                    if a.summary_grounding
                    and a.summary_grounding.get("status")
                    in ("grounded", "limited", "review_limited")
                    else None
                ),
            )
            for a in sorted(event.articles, key=lambda a: a.id)
        ],
        viewpoint=viewpoint_out(event.viewpoint, {a.id for a in event.articles}),
    )


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
        .options(selectinload(Event.articles), selectinload(Event.viewpoint))
        .order_by(func.coalesce(decayed, -1.0).desc(), Event.changed_at.desc())
        .limit(limit)
    ).all()
    source_names = {s.id: s.name for s in load_sources()}
    events: list[EventOut] = []
    for event, decayed_score in rows:
        events.append(
            event_out(
                event, float(decayed_score) if decayed_score is not None else None, source_names
            )
        )
    return EventsResponse(events=events)
