"""Read-only admin home assembled from the existing query definitions."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from unspun.api.admin.content import count_articles
from unspun.api.admin.costs import get_costs
from unspun.api.admin.query import RangeDep
from unspun.api.admin.runs import get_backlog, run_out
from unspun.api.admin.sources import list_sources, source_summary
from unspun.api.events import get_db
from unspun.core.models import Article, Event, FetchLog, PipelineRun

router = APIRouter()
Db = Annotated[Session, Depends(get_db)]


@router.get("/overview")
def get_overview(period: RangeDep, session: Db) -> dict[str, object]:
    """Keep all period metrics on the same resolved interval and cost rules."""
    source_rows = list_sources(session, period.start, period.end)
    source_totals = source_summary(source_rows)
    costs = get_costs(period, session)
    backlog = get_backlog(session, page_size=1)
    recent_run = session.scalar(
        select(PipelineRun)
        .where(PipelineRun.run_at < period.as_of)
        .order_by(PipelineRun.run_at.desc(), PipelineRun.id.desc())
        .limit(1)
    )
    article_day = func.date(func.timezone("Asia/Shanghai", Article.fetched_at))
    article_trend = [
        {"day": day.isoformat(), "articles": count}
        for day, count in session.execute(
            select(article_day, func.count(Article.id))
            .where(Article.fetched_at >= period.start, Article.fetched_at < period.end)
            .group_by(article_day)
            .order_by(article_day)
        )
    ]
    errors = sorted(
        (row for row in source_rows if row["health"] == "error"),
        key=lambda row: row["last_error_at"] or datetime.min.replace(tzinfo=period.start.tzinfo),
        reverse=True,
    )
    return {
        "range": costs["range"],
        "as_of": period.as_of,
        "period": {
            "articles": count_articles(session, period.start, period.end),
            "new_events": session.scalar(
                select(func.count(Event.id)).where(
                    Event.first_seen_at >= period.start, Event.first_seen_at < period.end
                )
            )
            or 0,
            "runs": session.scalar(
                select(func.count(PipelineRun.id)).where(
                    PipelineRun.run_at >= period.start, PipelineRun.run_at < period.end
                )
            )
            or 0,
            "fetch_errors": session.scalar(
                select(func.count(FetchLog.id)).where(
                    FetchLog.run_at >= period.start,
                    FetchLog.run_at < period.end,
                    FetchLog.status == "error",
                )
            )
            or 0,
            "sources": source_totals,
            "cost": {
                "total_confirmed_usd": costs["total_confirmed_usd"],
                "calls": costs["calls"],
                "fixed": costs["fixed"],
            },
        },
        "current": {
            "scope": "current",
            "consistency": "live",
            "source_health": {
                "error": sum(row["health"] == "error" for row in source_rows),
                "no_runs": sum(row["health"] == "no_runs" for row in source_rows),
                "ok": sum(row["health"] == "ok" for row in source_rows),
            },
            "backlog": backlog.counts,
        },
        "article_trend": article_trend,
        "call_trend": costs["trend"],
        "purposes": costs["purposes"],
        "recent_run": run_out(recent_run) if recent_run else None,
        "exceptions": {
            "sources": [
                {
                    "source_id": row["id"],
                    "name": row["name"] or row["id"],
                    "last_error": row["last_error"],
                    "last_error_at": row["last_error_at"],
                }
                for row in errors[:5]
            ],
            "source_error_total": len(errors),
            "abandoned_summaries": backlog.counts.abandoned_summaries,
        },
    }
