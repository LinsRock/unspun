"""Daily run report: failing sources and LLM spend (M1 acceptance input)."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from unspun.api.events import get_db
from unspun.core.models import FetchLog, LlmUsage

router = APIRouter()

REPORT_WINDOW_HOURS = 24


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


class ReportResponse(BaseModel):
    window_hours: int
    generated_at: datetime
    fetch_runs: int
    new_articles: int
    source_failures: list[SourceFailure]
    llm_spend: list[LlmSpend]
    llm_cost_total_usd: float


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

    llm_spend = [
        LlmSpend(
            purpose=row[0],
            model=row[1],
            calls=row[2],
            prompt_tokens=row[3],
            completion_tokens=row[4],
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
    )
