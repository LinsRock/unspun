"""Read-only admin home assembled from the existing query definitions."""

from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from unspun.api.admin.content import count_articles
from unspun.api.admin.costs import get_costs
from unspun.api.admin.query import RangeDep
from unspun.api.admin.runs import get_backlog, run_out
from unspun.api.admin.sources import list_sources, source_summary
from unspun.api.events import get_db
from unspun.core.models import Article, Event, FetchLog, LlmUsage, PipelineRun

router = APIRouter()
Db = Annotated[Session, Depends(get_db)]
Granularity = Literal["auto", "hour", "day", "month"]
BucketSize = Literal["hour", "day", "month"]
BEIJING = ZoneInfo("Asia/Shanghai")


def _granularity(start: datetime, end: datetime, requested: Granularity) -> BucketSize:
    if requested != "auto":
        return requested
    local_start, local_end = start.astimezone(BEIJING), end.astimezone(BEIJING)
    if local_start.date() == local_end.date():
        return "hour"
    if (local_end - local_start).days >= 300:
        return "month"
    return "day"


def _bucket_label(timestamp: datetime, granularity: BucketSize) -> str:
    local = (
        timestamp.replace(tzinfo=BEIJING)
        if timestamp.tzinfo is None
        else timestamp.astimezone(BEIJING)
    )
    pattern = (
        "%Y-%m"
        if granularity == "month"
        else "%Y-%m-%d %H:00"
        if granularity == "hour"
        else "%Y-%m-%d"
    )
    return local.strftime(pattern)


def _bucket_labels(start: datetime, end: datetime, granularity: BucketSize) -> list[str]:
    cursor = start.astimezone(BEIJING)
    if granularity == "month":
        cursor = cursor.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elif granularity == "day":
        cursor = cursor.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        cursor = cursor.replace(minute=0, second=0, microsecond=0)
    end_local = end.astimezone(BEIJING)
    labels: list[str] = []
    while cursor < end_local:
        labels.append(_bucket_label(cursor, granularity))
        if granularity == "month":
            cursor = cursor.replace(
                year=cursor.year + int(cursor.month == 12), month=cursor.month % 12 + 1
            )
        elif granularity == "day":
            cursor += timedelta(days=1)
        else:
            cursor += timedelta(hours=1)
    return labels


@router.get("/overview")
def get_overview(
    period: RangeDep, session: Db, granularity: Granularity = "auto"
) -> dict[str, object]:
    """Keep all period metrics on the same resolved interval and cost rules."""
    source_rows = list_sources(session, period.start, period.end)
    source_totals = source_summary(source_rows)
    current_sources = [row for row in source_rows if row["configured"] and row["enabled"]]
    current_errors = sorted(
        (row for row in current_sources if row["health"] == "error"),
        key=lambda row: row["last_error_at"] or datetime.min.replace(tzinfo=period.start.tzinfo),
        reverse=True,
    )
    costs = get_costs(period, session)
    backlog = get_backlog(session, page_size=1)
    recent_run = session.scalar(
        select(PipelineRun)
        .where(PipelineRun.run_at < period.as_of)
        .order_by(PipelineRun.run_at.desc(), PipelineRun.id.desc())
        .limit(1)
    )

    bucket_size = _granularity(period.start, period.end, granularity)
    article_bucket = func.date_trunc(
        bucket_size, func.timezone("Asia/Shanghai", Article.fetched_at)
    )
    processing_status = case(
        (Article.event_id.is_not(None), "clustered"),
        (Article.embedding.is_not(None), "embedded"),
        (Article.summary_zh.is_not(None), "summarized"),
        (Article.summary_failures > 0, "failed"),
        else_="pending",
    )
    article_counts: dict[str, int] = defaultdict(int)
    processing_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for timestamp, status, count in session.execute(
        select(article_bucket, processing_status, func.count(Article.id))
        .where(Article.fetched_at >= period.start, Article.fetched_at < period.end)
        .group_by(article_bucket, processing_status)
        .order_by(article_bucket)
    ):
        key = _bucket_label(timestamp, bucket_size)
        article_counts[key] += count
        processing_counts[key][status] += count
    bucket_labels = _bucket_labels(period.start, period.end, bucket_size)
    article_trend = [{"day": key, "articles": article_counts.get(key, 0)} for key in bucket_labels]
    processing_trend = [
        {
            "day": key,
            **{
                stage: counts.get(stage, 0)
                for stage in ("pending", "failed", "summarized", "embedded", "clustered")
            },
        }
        for key in bucket_labels
        for counts in [processing_counts.get(key, {})]
    ]

    call_costs: dict[str, Decimal] = defaultdict(Decimal)
    purpose_costs: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for created_at, purpose, amount in session.execute(
        select(LlmUsage.created_at, LlmUsage.purpose, LlmUsage.cost_usd).where(
            LlmUsage.created_at >= period.start, LlmUsage.created_at < period.end
        )
    ):
        key = _bucket_label(created_at, bucket_size)
        cost = Decimal(str(amount))
        call_costs[key] += cost
        purpose_costs[key][purpose] += cost
    purposes = sorted({purpose for bucket in purpose_costs.values() for purpose in bucket})
    call_trend = [
        {"day": key, "cost_usd": str(call_costs.get(key, Decimal(0)))} for key in bucket_labels
    ]
    call_purpose_trend = [
        {
            "day": key,
            **{purpose: str(bucket.get(purpose, Decimal(0))) for purpose in purposes},
        }
        for key in bucket_labels
        for bucket in [purpose_costs.get(key, {})]
    ]

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
                "error": sum(row["health"] == "error" for row in current_sources),
                "no_runs": sum(row["health"] == "no_runs" for row in current_sources),
                "ok": sum(row["health"] == "ok" for row in current_sources),
            },
            "backlog": backlog.counts,
        },
        "granularity": bucket_size,
        "article_trend": article_trend,
        "processing_trend": processing_trend,
        "call_trend": call_trend,
        "call_purpose_trend": call_purpose_trend,
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
                for row in current_errors[:5]
            ],
            "source_error_total": len(current_errors),
            "abandoned_summaries": backlog.counts.abandoned_summaries,
        },
    }
