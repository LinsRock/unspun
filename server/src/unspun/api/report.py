"""Daily run report: failing sources, LLM spend, and pipeline backlog (M1 acceptance input)."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from unspun.api.events import get_db
from unspun.core.legacy_backlog import abandoned_summary_conditions, backlog_counts
from unspun.core.models import Article, FetchLog, LlmUsage, PipelineRun

router = APIRouter()

REPORT_WINDOW_HOURS = 24
ABANDONED_LIST_LIMIT = 100


class SourceFailure(BaseModel):
    source_id: str
    failures: int
    last_error: str | None


class LlmSpend(BaseModel):
    purpose: str
    model: str
    calls: int
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float


class AbandonedArticle(BaseModel):
    id: int
    title: str
    source_id: str


class PipelineBacklog(BaseModel):
    pending_summaries: int
    pending_embeddings: int
    pending_scores: int
    abandoned_total: int
    abandoned_articles: list[AbandonedArticle]


class LastRun(BaseModel):
    run_at: datetime
    summarized: int
    embedded: int
    clustered: int
    new_events: int
    scored: int


class ReportResponse(BaseModel):
    window_hours: int
    generated_at: datetime
    fetch_runs: int
    new_articles: int
    source_failures: list[SourceFailure]
    llm_spend: list[LlmSpend]
    llm_cost_total_usd: float
    backlog: PipelineBacklog
    last_run: LastRun | None


@router.get("/api/report/daily", response_model=ReportResponse)
def daily_report(session: Session = Depends(get_db)) -> ReportResponse:  # noqa: B008
    since = datetime.now(UTC) - timedelta(hours=REPORT_WINDOW_HOURS)

    totals = session.execute(
        select(func.count(), func.coalesce(func.sum(FetchLog.new_articles), 0)).where(
            FetchLog.run_at >= since
        )
    ).one()

    failures = session.execute(
        select(
            FetchLog.source_id,
            func.count().label("failures"),
            func.max(FetchLog.error).label("last_error"),
        )
        .where(FetchLog.run_at >= since, FetchLog.status == "error")
        .group_by(FetchLog.source_id)
        .order_by(func.count().desc())
    ).all()

    spend = session.execute(
        select(
            LlmUsage.purpose,
            LlmUsage.model,
            func.count().label("calls"),
            func.coalesce(func.sum(LlmUsage.prompt_tokens), 0),
            func.coalesce(func.sum(LlmUsage.completion_tokens), 0),
            func.coalesce(func.sum(LlmUsage.cost_usd), 0.0),
        )
        .where(LlmUsage.created_at >= since)
        .group_by(LlmUsage.purpose, LlmUsage.model)
        .order_by(func.sum(LlmUsage.cost_usd).desc())
    ).all()

    counts = backlog_counts(session)
    abandoned = session.execute(
        select(Article.id, Article.title, Article.source_id)
        .where(*abandoned_summary_conditions())
        .order_by(Article.id.desc())
        .limit(ABANDONED_LIST_LIMIT)
    ).all()
    last_run_row = session.scalars(
        select(PipelineRun).order_by(PipelineRun.run_at.desc(), PipelineRun.id.desc()).limit(1)
    ).first()

    llm_spend = [
        LlmSpend(
            purpose=row[0],
            model=row[1],
            calls=row[2],
            prompt_tokens=row[3] or 0,
            completion_tokens=row[4] or 0,
            cost_usd=float(row[5]),
        )
        for row in spend
    ]
    return ReportResponse(
        window_hours=REPORT_WINDOW_HOURS,
        generated_at=datetime.now(UTC),
        fetch_runs=totals[0],
        new_articles=int(totals[1]),
        source_failures=[
            SourceFailure(source_id=row[0], failures=row[1], last_error=row[2]) for row in failures
        ],
        llm_spend=llm_spend,
        llm_cost_total_usd=sum(s.cost_usd for s in llm_spend),
        backlog=PipelineBacklog(
            pending_summaries=counts["pending_summaries"],
            pending_embeddings=counts["pending_embeddings"],
            pending_scores=counts["pending_scores"],
            abandoned_total=counts["abandoned_summaries"],
            abandoned_articles=[
                AbandonedArticle(id=row[0], title=row[1], source_id=row[2]) for row in abandoned
            ],
        ),
        last_run=LastRun(
            run_at=last_run_row.run_at,
            summarized=last_run_row.summarized,
            embedded=last_run_row.embedded,
            clustered=last_run_row.clustered,
            new_events=last_run_row.new_events,
            scored=last_run_row.scored,
        )
        if last_run_row
        else None,
    )
