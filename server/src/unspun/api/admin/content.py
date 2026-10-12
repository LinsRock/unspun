"""Read-only article and event history, with full payloads only in details."""

from datetime import UTC, datetime
from typing import Any, Literal, cast

from fastapi import APIRouter, HTTPException
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, selectinload

from unspun.api.admin.query import Page, PageSize, RangeDep, page_result
from unspun.core.db import session_scope
from unspun.core.models import Article, Event
from unspun.core.sources import load_sources

router = APIRouter()
TimeBasis = Literal["fetched_at", "published_at"]
Order = Literal["newest", "oldest"]
ArticleStatus = Literal["pending", "failed", "summarized", "embedded", "clustered"]
EventStatus = Literal["pending", "scored"]


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _article_status(
    summarized: bool, failures: int, embedded: bool, event_id: int | None
) -> ArticleStatus:
    if event_id is not None:
        return "clustered"
    if embedded:
        return "embedded"
    if summarized:
        return "summarized"
    if failures:
        return "failed"
    return "pending"


def list_articles(
    session: Session,
    start: datetime,
    end: datetime,
    *,
    time_basis: TimeBasis = "fetched_at",
    keyword: str | None = None,
    source_id: str | None = None,
    lang: str | None = None,
    processing_status: ArticleStatus | None = None,
    quality_status: str | None = None,
    sort: Order = "newest",
) -> list[dict[str, Any]]:
    time_column = Article.fetched_at if time_basis == "fetched_at" else Article.published_at
    quality_column = Article.summary_grounding["status"].astext
    stmt = select(
        Article.id,
        Article.source_id,
        Article.url,
        Article.title,
        Article.title_zh,
        Article.lang,
        Article.published_at,
        Article.fetched_at,
        Article.summary_zh.is_not(None).label("has_summary"),
        Article.summary_failures,
        Article.embedding.is_not(None).label("has_embedding"),
        Article.event_id,
        quality_column.label("quality_status"),
    ).where(time_column >= start, time_column < end)
    if keyword:
        pattern = f"%{_escape_like(keyword)}%"
        stmt = stmt.where(
            or_(
                Article.title.ilike(pattern, escape="\\"),
                Article.title_zh.ilike(pattern, escape="\\"),
            )
        )
    if source_id:
        stmt = stmt.where(Article.source_id == source_id)
    if lang:
        stmt = stmt.where(Article.lang == lang)
    if quality_status:
        stmt = stmt.where(
            quality_column.is_(None)
            if quality_status == "unrecorded"
            else quality_column == quality_status
        )
    stmt = stmt.order_by(
        time_column.desc().nulls_last() if sort == "newest" else time_column.asc().nulls_last(),
        Article.id.desc() if sort == "newest" else Article.id.asc(),
    )
    source_names = {source.id: source.name for source in load_sources()}
    rows: list[dict[str, Any]] = []
    for row in session.execute(stmt).mappings():
        status = _article_status(
            row["has_summary"], row["summary_failures"], row["has_embedding"], row["event_id"]
        )
        if processing_status and status != processing_status:
            continue
        rows.append(
            {
                "id": row["id"],
                "source_id": row["source_id"],
                "source_name": source_names.get(row["source_id"]),
                "url": row["url"],
                "title": row["title"],
                "title_zh": row["title_zh"],
                "lang": row["lang"],
                "published_at": row["published_at"],
                "fetched_at": row["fetched_at"],
                "summary_status": "done"
                if row["has_summary"]
                else "failed"
                if row["summary_failures"]
                else "pending",
                "embedding_status": "done" if row["has_embedding"] else "pending",
                "cluster_status": "done" if row["event_id"] is not None else "pending",
                "processing_status": status,
                "quality_status": row["quality_status"] or "unrecorded",
                "event_id": row["event_id"],
            }
        )
    return rows


def read_article(session: Session, article_id: int) -> dict[str, Any] | None:
    article = session.get(Article, article_id)
    if article is None:
        return None
    source = next((source for source in load_sources() if source.id == article.source_id), None)
    return {
        "id": article.id,
        "source_id": article.source_id,
        "source_name": source.name if source else None,
        "url": article.url,
        "title": article.title,
        "title_zh": article.title_zh,
        "lang": article.lang,
        "published_at": article.published_at,
        "fetched_at": article.fetched_at,
        "content": article.content,
        "summary_zh": article.summary_zh,
        "summary_grounding": article.summary_grounding,
        "summary_failures": article.summary_failures,
        "embedding_status": "done" if article.embedding is not None else "pending",
        "event_id": article.event_id,
        "event": {"id": article.event.id, "title": article.event.title} if article.event else None,
        "call_cost": None,  # Historical LLM usage has no object link.
    }


def _event_aggregates(session: Session, as_of: datetime) -> Any:
    valid_publication = case((Article.published_at <= as_of, Article.published_at))
    return (
        select(
            Article.event_id.label("event_id"),
            func.count(Article.id).label("article_count"),
            func.count(func.distinct(Article.source_id)).label("source_count"),
            func.min(valid_publication).label("earliest_published_at"),
            func.max(valid_publication).label("latest_published_at"),
        )
        .where(Article.event_id.is_not(None))
        .group_by(Article.event_id)
        .subquery()
    )


def list_events(
    session: Session,
    start: datetime,
    end: datetime,
    *,
    keyword: str | None = None,
    source_id: str | None = None,
    processing_status: EventStatus | None = None,
    sort: Order = "newest",
    as_of: datetime | None = None,
) -> list[dict[str, Any]]:
    snapshot = as_of or datetime.now(UTC)
    agg = _event_aggregates(session, snapshot)
    # Unknown report time is explicit in the response; first_seen_at only
    # selects it into a historical admin range, never poses as publication.
    range_time = func.coalesce(agg.c.earliest_published_at, Event.first_seen_at)
    stmt = (
        select(
            Event.id,
            Event.title,
            Event.first_seen_at,
            Event.changed_at,
            Event.score_final,
            Event.scored_at,
            agg.c.article_count,
            agg.c.source_count,
            agg.c.earliest_published_at,
            agg.c.latest_published_at,
        )
        .outerjoin(agg, Event.id == agg.c.event_id)
        .where(range_time >= start, range_time < end)
    )
    if keyword:
        stmt = stmt.where(Event.title.ilike(f"%{_escape_like(keyword)}%", escape="\\"))
    if source_id:
        stmt = stmt.where(
            select(Article.id)
            .where(Article.event_id == Event.id, Article.source_id == source_id)
            .exists()
        )
    if processing_status == "scored":
        stmt = stmt.where(Event.scored_at.is_not(None), Event.scored_at >= Event.changed_at)
    elif processing_status == "pending":
        stmt = stmt.where(or_(Event.scored_at.is_(None), Event.scored_at < Event.changed_at))
    stmt = stmt.order_by(
        agg.c.earliest_published_at.desc().nulls_last()
        if sort == "newest"
        else agg.c.earliest_published_at.asc().nulls_last(),
        Event.id.desc() if sort == "newest" else Event.id.asc(),
    )
    rows: list[dict[str, Any]] = []
    for row in session.execute(stmt).mappings():
        status: EventStatus = (
            "scored" if row["scored_at"] and row["scored_at"] >= row["changed_at"] else "pending"
        )
        rows.append(
            {
                "id": row["id"],
                "title": row["title"],
                "first_seen_at": row["first_seen_at"],
                "changed_at": row["changed_at"],
                "earliest_published_at": row["earliest_published_at"],
                "latest_published_at": row["latest_published_at"],
                "article_count": row["article_count"] or 0,
                "source_count": row["source_count"] or 0,
                "score_final": row["score_final"],
                "scored_at": row["scored_at"],
                "processing_status": status,
            }
        )
    return rows


def _safe_viewpoint(payload: dict[str, Any], allowed_ids: set[int]) -> dict[str, Any]:
    result = dict(payload)
    claims = payload.get("claims")
    if not isinstance(claims, list):
        return result
    index_map: dict[int, int] = {}
    kept: list[dict[str, Any]] = []
    for index, raw in enumerate(cast("list[Any]", claims)):
        if (
            isinstance(raw, dict)
            and type(cast("dict[str, Any]", raw).get("article_id")) is int
            and cast("dict[str, Any]", raw)["article_id"] in allowed_ids
        ):
            index_map[index] = len(kept)
            kept.append(cast("dict[str, Any]", raw))
    result["claims"] = kept
    disagreements = payload.get("disagreements")
    if isinstance(disagreements, list):
        safe_disagreements: list[dict[str, Any]] = []
        for raw in cast("list[Any]", disagreements):
            if not isinstance(raw, dict) or not isinstance(
                cast("dict[str, Any]", raw).get("claim_indexes"), list
            ):
                continue
            entry = cast("dict[str, Any]", raw)
            indexes = sorted(
                {
                    index_map[i]
                    for i in cast("list[Any]", entry["claim_indexes"])
                    if type(i) is int and i in index_map
                }
            )
            if len(indexes) >= 2:
                safe_disagreements.append({**entry, "claim_indexes": indexes})
        result["disagreements"] = safe_disagreements
    return result


def read_event(session: Session, event_id: int) -> dict[str, Any] | None:
    event = session.get(
        Event, event_id, options=[selectinload(Event.articles), selectinload(Event.viewpoint)]
    )
    if event is None:
        return None
    articles = sorted(event.articles, key=lambda a: (a.published_at or a.fetched_at, a.id))
    valid_times = [
        a.published_at for a in articles if a.published_at and a.published_at <= datetime.now(UTC)
    ]
    source_names = {source.id: source.name for source in load_sources()}
    viewpoint = event.viewpoint
    return {
        "id": event.id,
        "title": event.title,
        "summary_zh": event.summary_zh,
        "score_final": event.score_final,
        "score_breakdown": event.score_breakdown,
        "scored_at": event.scored_at,
        "first_seen_at": event.first_seen_at,
        "changed_at": event.changed_at,
        "earliest_published_at": min(valid_times) if valid_times else None,
        "latest_published_at": max(valid_times) if valid_times else None,
        "article_count": len(articles),
        "source_count": len({a.source_id for a in articles}),
        "articles": [
            {
                "id": a.id,
                "source_id": a.source_id,
                "source_name": source_names.get(a.source_id),
                "title": a.title,
                "url": a.url,
                "published_at": a.published_at,
                "fetched_at": a.fetched_at,
                "summary_zh": a.summary_zh,
                "summary_grounding": a.summary_grounding,
            }
            for a in articles
        ],
        "viewpoint": {
            "payload": _safe_viewpoint(viewpoint.payload, {a.id for a in articles}),
            "model": viewpoint.model,
            "generated_at": viewpoint.generated_at,
        }
        if viewpoint
        else None,
        "processing_records": None,  # No per-object history exists yet.
    }


@router.get("/articles")
def get_articles(
    period: RangeDep,
    page: Page = 1,
    page_size: PageSize = 25,
    time_basis: TimeBasis = "fetched_at",
    keyword: str | None = None,
    source_id: str | None = None,
    lang: str | None = None,
    processing_status: ArticleStatus | None = None,
    quality_status: str | None = None,
    sort: Order = "newest",
) -> dict[str, object]:
    with session_scope() as session:
        rows = list_articles(
            session,
            period.start,
            period.end,
            time_basis=time_basis,
            keyword=keyword,
            source_id=source_id,
            lang=lang,
            processing_status=processing_status,
            quality_status=quality_status,
            sort=sort,
        )
        return page_result(cast("list[dict[str, object]]", rows), period, page, page_size)


@router.get("/articles/{article_id}")
def get_article(article_id: int) -> dict[str, Any]:
    with session_scope() as session:
        row = read_article(session, article_id)
        if row is None:
            raise HTTPException(status_code=404, detail="article not found")
        return row


@router.get("/events")
def get_events(
    period: RangeDep,
    page: Page = 1,
    page_size: PageSize = 25,
    keyword: str | None = None,
    source_id: str | None = None,
    processing_status: EventStatus | None = None,
    sort: Order = "newest",
) -> dict[str, object]:
    with session_scope() as session:
        rows = list_events(
            session,
            period.start,
            period.end,
            keyword=keyword,
            source_id=source_id,
            processing_status=processing_status,
            sort=sort,
            as_of=period.as_of,
        )
        return page_result(cast("list[dict[str, object]]", rows), period, page, page_size)


@router.get("/events/{event_id}")
def get_event(event_id: int) -> dict[str, Any]:
    with session_scope() as session:
        row = read_event(session, event_id)
        if row is None:
            raise HTTPException(status_code=404, detail="event not found")
        return row
