"""Bounded, filtered, spreadsheet-safe admin CSV exports."""

import csv
from collections.abc import Iterator
from datetime import datetime
from io import StringIO
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from unspun.api.admin.content import (
    ArticleStatus,
    EventStatus,
    EventTimeStatus,
    Order,
    TimeBasis,
    list_articles,
    list_events,
)
from unspun.api.admin.query import RangeDep
from unspun.api.admin.sources import SourceHealth, SourceSort, filter_sources, list_sources
from unspun.core.db import session_scope

router = APIRouter()
EXPORT_LIMIT = 5000

SOURCE_COLUMNS = [
    "id",
    "name",
    "lang",
    "region",
    "kind",
    "configured",
    "enabled",
    "health",
    "latest_status",
    "period_latest_status",
    "article_count",
    "new_articles",
    "successful_fetches",
    "failed_fetches",
    "success_rate",
    "last_success_at",
    "last_error_at",
    "last_error",
]
ARTICLE_COLUMNS = [
    "id",
    "source_id",
    "source_name",
    "url",
    "title",
    "title_zh",
    "lang",
    "published_at",
    "fetched_at",
    "summary_status",
    "embedding_status",
    "cluster_status",
    "quality_status",
    "event_id",
]
EVENT_COLUMNS = [
    "id",
    "title",
    "first_seen_at",
    "earliest_published_at",
    "latest_published_at",
    "article_count",
    "source_count",
    "score_final",
    "scored_at",
    "processing_status",
    "range_time_basis",
]


def safe_cell(value: object) -> str:
    if value is None:
        return ""
    result = value.isoformat() if isinstance(value, datetime) else str(value)
    if result.lstrip().startswith(("=", "+", "-", "@", "\t", "\r", "\n")):
        return "'" + result
    return result


def csv_lines(
    rows: list[dict[str, Any]], columns: list[str], *, limit: int = EXPORT_LIMIT
) -> Iterator[str]:
    if len(rows) > limit:
        raise ValueError("export has too many matching rows; choose narrower filters")
    buffer = StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(columns)
    yield buffer.getvalue()
    for row in rows:
        buffer.seek(0)
        buffer.truncate(0)
        writer.writerow([safe_cell(row.get(column)) for column in columns])
        yield buffer.getvalue()


def _response(rows: list[dict[str, Any]], columns: list[str], filename: str) -> StreamingResponse:
    if len(rows) > EXPORT_LIMIT:
        raise HTTPException(
            status_code=422, detail="too many matching rows; choose narrower filters"
        )
    return StreamingResponse(
        csv_lines(rows, columns, limit=EXPORT_LIMIT),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/sources/export.csv")
def export_sources(
    period: RangeDep,
    keyword: str | None = None,
    lang: str | None = None,
    region: str | None = None,
    kind: str | None = None,
    configured: bool | None = None,
    enabled: bool | None = None,
    health: SourceHealth | None = None,
    sort: SourceSort = "health",
) -> StreamingResponse:
    with session_scope() as session:
        rows = filter_sources(
            list_sources(session, period.start, period.end),
            keyword=keyword,
            lang=lang,
            region=region,
            kind=kind,
            configured=configured,
            enabled=enabled,
            health=health,
            sort=sort,
        )
    return _response(rows, SOURCE_COLUMNS, "sources.csv")


@router.get("/articles/export.csv")
def export_articles(
    period: RangeDep,
    time_basis: TimeBasis = "fetched_at",
    keyword: str | None = None,
    source_id: str | None = None,
    lang: str | None = None,
    processing_status: ArticleStatus | None = None,
    quality_status: str | None = None,
    sort: Order = "newest",
) -> StreamingResponse:
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
            limit=EXPORT_LIMIT + 1,
        )
    return _response(rows, ARTICLE_COLUMNS, "articles.csv")


@router.get("/events/export.csv")
def export_events(
    period: RangeDep,
    keyword: str | None = None,
    source_id: str | None = None,
    processing_status: EventStatus | None = None,
    time_status: EventTimeStatus = "reported",
    sort: Order = "newest",
) -> StreamingResponse:
    with session_scope() as session:
        rows = list_events(
            session,
            period.start,
            period.end,
            keyword=keyword,
            source_id=source_id,
            processing_status=processing_status,
            time_status=time_status,
            sort=sort,
            as_of=period.as_of,
            limit=EXPORT_LIMIT + 1,
        )
    return _response(rows, EVENT_COLUMNS, "events.csv")
