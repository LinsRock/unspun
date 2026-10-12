"""Read-only source history from current configuration and recorded outcomes."""

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from unspun.api.admin.query import Page, PageSize, RangeDep, page_result
from unspun.core.db import session_scope
from unspun.core.models import Article, FetchLog
from unspun.core.sources import load_sources

router = APIRouter()
SourceSort = Literal["health", "articles", "failure_rate", "last_success", "name"]
SourceHealth = Literal["ok", "error", "no_runs"]


def list_sources(session: Session, start: datetime, end: datetime) -> list[dict[str, Any]]:
    """Combine current IDs with historical IDs, without inventing old config."""
    current = {source.id: source for source in load_sources()}
    ids = (
        set(current)
        | set(session.scalars(select(FetchLog.source_id).distinct()))
        | set(session.scalars(select(Article.source_id).distinct()))
    )
    period_counts = {
        row.source_id: row
        for row in session.execute(
            select(
                FetchLog.source_id,
                func.count().filter(FetchLog.status == "ok").label("successes"),
                func.count().filter(FetchLog.status == "error").label("failures"),
                func.coalesce(
                    func.sum(FetchLog.new_articles).filter(FetchLog.status == "ok"), 0
                ).label("new_articles"),
            )
            .where(FetchLog.run_at >= start, FetchLog.run_at < end)
            .group_by(FetchLog.source_id)
        )
    }
    article_counts = {
        source_id: count
        for source_id, count in session.execute(
            select(Article.source_id, func.count(Article.id))
            .where(Article.fetched_at >= start, Article.fetched_at < end)
            .group_by(Article.source_id)
        )
    }

    def latest_by_source(*, status: str | None = None, period: bool = False) -> dict[str, FetchLog]:
        stmt = select(FetchLog).ext(distinct_on(FetchLog.source_id))
        if status is not None:
            stmt = stmt.where(FetchLog.status == status)
        if period:
            stmt = stmt.where(FetchLog.run_at >= start, FetchLog.run_at < end)
        stmt = stmt.order_by(FetchLog.source_id, FetchLog.run_at.desc(), FetchLog.id.desc())
        return {log.source_id: log for log in session.scalars(stmt)}

    latest = latest_by_source()
    latest_errors = latest_by_source(status="error")
    latest_successes = latest_by_source(status="ok")
    period_latest = latest_by_source(period=True)
    rows: list[dict[str, Any]] = []
    for source_id in ids:
        source = current.get(source_id)
        counts = period_counts.get(source_id)
        successes = counts.successes if counts else 0
        failures = counts.failures if counts else 0
        latest_error = latest_errors.get(source_id)
        latest_success = latest_successes.get(source_id)
        latest_run = latest.get(source_id)
        health: SourceHealth = (
            "no_runs" if latest_run is None else "error" if latest_run.status == "error" else "ok"
        )
        rows.append(
            {
                "id": source_id,
                "name": source.name if source else None,
                "lang": source.lang if source else None,
                "region": source.region if source else None,
                "kind": source.kind if source else None,
                "configured": source is not None,
                "enabled": source is not None,
                "health": health,
                "article_count": article_counts.get(source_id, 0),
                "new_articles": counts.new_articles if counts else 0,
                "successful_fetches": successes,
                "failed_fetches": failures,
                "success_rate": successes / (successes + failures)
                if successes + failures
                else None,
                "last_success_at": latest_success.run_at if latest_success else None,
                "last_error_at": latest_error.run_at if latest_error else None,
                "last_error": latest_error.error if latest_error else None,
                "latest_status": latest_run.status if latest_run else None,
                "period_latest_status": period_latest[source_id].status
                if source_id in period_latest
                else None,
            }
        )
    return rows


def filter_sources(
    rows: list[dict[str, Any]],
    *,
    keyword: str | None = None,
    lang: str | None = None,
    region: str | None = None,
    kind: str | None = None,
    configured: bool | None = None,
    enabled: bool | None = None,
    health: SourceHealth | None = None,
    sort: SourceSort = "health",
) -> list[dict[str, Any]]:
    if keyword:
        folded = keyword.casefold()
        rows = [r for r in rows if folded in str(r["name"] or r["id"]).casefold()]
    for key, value in (("lang", lang), ("region", region), ("kind", kind)):
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    if configured is not None:
        rows = [r for r in rows if r["configured"] is configured]
    if enabled is not None:
        rows = [r for r in rows if r["enabled"] is enabled]
    if health is not None:
        rows = [r for r in rows if r["health"] == health]
    # A second id ordering makes every sort deterministic, including ties/nulls.
    rows.sort(key=lambda r: str(r["id"]))
    if sort == "health":
        rows.sort(key=lambda r: {"error": 0, "no_runs": 1, "ok": 2}[str(r["health"])])
    elif sort == "articles":
        rows.sort(key=lambda r: int(r["article_count"]), reverse=True)
    elif sort == "failure_rate":
        rows.sort(
            key=lambda r: float(1 - r["success_rate"]) if r["success_rate"] is not None else -1.0,
            reverse=True,
        )
    elif sort == "last_success":
        rows.sort(
            key=lambda r: r["last_success_at"] or datetime.min.replace(tzinfo=UTC), reverse=True
        )
    else:
        rows.sort(key=lambda r: str(r["name"] or r["id"]).casefold())
    return rows


def source_summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Full filtered result counts, independent of pagination."""
    return {
        "configured_total": sum(r["configured"] is True for r in rows),
        "enabled_total": sum(r["enabled"] is True for r in rows),
        "successful_sources": sum(int(r["successful_fetches"]) > 0 for r in rows),
        "productive_sources": sum(int(r["new_articles"]) > 0 for r in rows),
        "failed_sources": sum(int(r["failed_fetches"]) > 0 for r in rows),
    }


@router.get("/sources")
def get_sources(
    period: RangeDep,
    page: Page = 1,
    page_size: PageSize = 25,
    keyword: str | None = None,
    lang: str | None = None,
    region: str | None = None,
    kind: str | None = None,
    configured: bool | None = None,
    enabled: bool | None = None,
    health: SourceHealth | None = None,
    sort: SourceSort = "health",
) -> dict[str, object]:
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
        return {**page_result(rows, period, page, page_size), "summary": source_summary(rows)}


@router.get("/sources/{source_id}")
def get_source(source_id: str, period: RangeDep) -> dict[str, object]:
    with session_scope() as session:
        rows = list_sources(session, period.start, period.end)
        row = next((item for item in rows if item["id"] == source_id), None)
        if row is None:
            raise HTTPException(status_code=404, detail="source not found")
        config = next((item for item in load_sources() if item.id == source_id), None)
        fetches = session.scalars(
            select(FetchLog)
            .where(
                FetchLog.source_id == source_id,
                FetchLog.run_at >= period.start,
                FetchLog.run_at < period.end,
            )
            .order_by(FetchLog.run_at.desc(), FetchLog.id.desc())
            .limit(100)
        ).all()
        article_rows = session.execute(
            select(Article.id, Article.title, Article.fetched_at, Article.event_id)
            .where(
                Article.source_id == source_id,
                Article.fetched_at >= period.start,
                Article.fetched_at < period.end,
            )
            .order_by(Article.fetched_at.desc(), Article.id.desc())
            .limit(100)
        ).all()
        return {
            **row,
            "config": {
                "url": str(config.url),
                "weight": config.weight,
                "max_items": config.max_items,
                "timeout_seconds": config.timeout_seconds,
            }
            if config
            else None,
            "fetches": [
                {
                    "id": log.id,
                    "run_at": log.run_at,
                    "status": log.status,
                    "new_articles": log.new_articles,
                    "error": log.error,
                }
                for log in fetches
            ],
            "articles": [
                {"id": id_, "title": title, "fetched_at": fetched_at, "event_id": event_id}
                for id_, title, fetched_at, event_id in article_rows
            ],
        }
