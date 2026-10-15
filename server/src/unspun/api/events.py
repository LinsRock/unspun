"""Live event stream endpoint: scored events with time-decayed ordering."""

import math
from collections.abc import Generator
from datetime import UTC, date, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session, selectinload

from unspun.api.admin.auth import require_admin_identity
from unspun.core.db import session_scope
from unspun.core.feed_query import RANKING_VERSION, feed_page
from unspun.core.logging import get_logger
from unspun.core.models import Event, EventReadState, EventViewpoint
from unspun.core.params import get_scoring_params
from unspun.core.sources import load_sources

router = APIRouter()

log = get_logger("unspun.api.events")

LN2 = math.log(2.0)


def get_db() -> Generator[Session]:
    with session_scope() as session:
        # One request observes one MVCC snapshot across generation, ranking and DTO queries.
        session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        session.execute(text("SET TRANSACTION READ ONLY"))
        yield session


def get_feed_now() -> datetime:
    return datetime.now(UTC)


class ArticleOut(BaseModel):
    id: int
    title: str
    title_zh: str | None
    url: str
    source_id: str
    source_name: str
    published_at: datetime | None
    reported_at: datetime | None = None
    reported_date: date | None = None
    reported_precision: str = "unknown"
    reported_basis: str | None = None
    publisher_group: str | None = None
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
    earliest_reported_at: datetime | None = None
    earliest_reported_date: date | None = None
    earliest_reported_precision: str = "unknown"
    latest_reported_at: datetime | None = None
    latest_reported_date: date | None = None
    latest_reported_precision: str = "unknown"
    reported_time_basis: str = "original"
    valid_time_count: int = 0
    missing_time_count: int = 0
    invalid_time_count: int = 0
    active_publishers: int = 0
    heat: float | None = None
    ranking_metric: float | None = None
    public_impact_boosted: bool = False
    is_read: bool = False
    read_at: datetime | None = None
    read_version: int = 0


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
    next_cursor: str | None
    as_of: datetime
    sort: str
    range: str
    window_start: datetime | None
    window_end: datetime
    ranking_version: str = RANKING_VERSION


def event_out(
    event: Event,
    decayed_score: float | None,
    source_names: dict[str, str],
    as_of: datetime | None = None,
) -> EventOut:
    """Serialize a live event or a digest snapshot with the same provenance rules."""
    articles = [a for a in event.articles if as_of is None or a.fetched_at <= as_of]
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
                reported_at=a.reported_at,
                reported_date=a.reported_date,
                reported_precision=a.reported_precision,
                reported_basis=a.reported_basis,
                publisher_group=a.publisher_group,
                content_quality=(
                    a.summary_grounding.get("status")
                    if a.summary_grounding
                    and a.summary_grounding.get("status")
                    in ("grounded", "limited", "review_limited")
                    else None
                ),
            )
            for a in sorted(articles, key=lambda a: a.id)
        ],
        viewpoint=viewpoint_out(event.viewpoint, {a.id for a in articles}),
    )


@router.get(
    "/api/events", response_model=EventsResponse, dependencies=[Depends(require_admin_identity)]
)
def list_events(
    limit: int = Query(default=50, ge=1, le=100),
    sort: Literal["newest", "hot", "important"] = "newest",
    range_: Literal["today", "24h", "7d", "all"] = Query(default="7d", alias="range"),
    unread_only: bool = False,
    cursor: str | None = Query(default=None, max_length=2048),
    session: Session = Depends(get_db),  # noqa: B008
    now: datetime = Depends(get_feed_now),  # noqa: B008
) -> EventsResponse:
    page = feed_page(session, sort, range_, limit, now, cursor, unread_only)
    ids = [row["id"] for row in page.rows]
    events_by_id = {
        event.id: event
        for event in session.scalars(
            select(Event)
            .where(Event.id.in_(ids))
            .options(selectinload(Event.articles), selectinload(Event.viewpoint))
        )
    }
    states = {
        r.event_id: r
        for r in session.scalars(select(EventReadState).where(EventReadState.event_id.in_(ids)))
    }
    source_names = {s.id: s.name for s in load_sources()}
    events: list[EventOut] = []
    for row in page.rows:
        event = events_by_id[row["id"]]
        age = (page.as_of - event.changed_at).total_seconds() / 3600
        decayed = (
            event.score_final * math.exp(-LN2 * age / get_scoring_params().stream.half_life_hours)
            if event.score_final is not None
            else None
        )
        out = event_out(event, decayed, source_names, page.as_of)
        for field in (
            "earliest_reported_at",
            "earliest_reported_date",
            "earliest_reported_precision",
            "latest_reported_at",
            "latest_reported_date",
            "latest_reported_precision",
            "valid_time_count",
            "missing_time_count",
            "invalid_time_count",
            "active_publishers",
            "heat",
        ):
            setattr(
                out,
                field,
                row[field] if row[field] is not None else (0 if field.endswith("count") else None),
            )
        if state := states.get(event.id):
            out.is_read, out.read_at, out.read_version = state.is_read, state.read_at, state.version
        out.ranking_metric = float(row["metric"]) if row["known"] else None
        out.public_impact_boosted = bool(row["boosted"])
        events.append(out)
    return EventsResponse(
        events=events,
        next_cursor=page.next_cursor,
        as_of=page.as_of,
        sort=sort,
        range=range_,
        window_start=page.start,
        window_end=page.as_of,
        ranking_version=page.version,
    )
