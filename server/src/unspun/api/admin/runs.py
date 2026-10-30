"""Read-only views over recorded AI cycles and the current pipeline backlog."""

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from unspun.api.admin.ranges import resolve_range
from unspun.api.admin.schemas import AdminRangeOut
from unspun.api.events import get_db
from unspun.core.legacy_backlog import (
    abandoned_summary_conditions,
    backlog_counts,
    pending_embedding_conditions,
    pending_score_conditions,
    pending_summary_conditions,
    summary_ordering,
)
from unspun.core.models import Article, Event, PipelineRun
from unspun.core.reading import publication_counts

router = APIRouter()
MISSING_RUN_FIELDS = ["ended_at", "duration_seconds", "status", "stage_results", "cost_usd"]


class RunOut(BaseModel):
    id: int
    run_at: datetime
    summarized: int
    embedded: int
    clustered: int
    new_events: int
    scored: int
    ended_at: datetime | None = None
    duration_seconds: float | None = None
    status: str | None = None
    stage_results: None = None
    cost_usd: float | None = None
    missing_fields: list[str]


class RunsOut(BaseModel):
    range: AdminRangeOut
    as_of: datetime
    total: int
    page: int
    page_size: int
    items: list[RunOut]


def run_out(run: PipelineRun) -> RunOut:
    return RunOut(
        id=run.id,
        run_at=run.run_at,
        summarized=run.summarized,
        embedded=run.embedded,
        clustered=run.clustered,
        new_events=run.new_events,
        scored=run.scored,
        missing_fields=MISSING_RUN_FIELDS,
    )


@router.get("/runs", response_model=RunsOut)
def list_runs(
    session: Annotated[Session, Depends(get_db)],
    start: datetime | None = None,
    end: datetime | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> RunsOut:
    try:
        resolved = resolve_range(start, end, datetime.now(UTC))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    conditions = (PipelineRun.run_at >= resolved.start, PipelineRun.run_at < resolved.end)
    total = session.scalar(select(func.count()).select_from(PipelineRun).where(*conditions)) or 0
    runs = session.scalars(
        select(PipelineRun)
        .where(*conditions)
        .order_by(PipelineRun.run_at.desc(), PipelineRun.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return RunsOut(
        range=AdminRangeOut(start=resolved.start, end=resolved.end),
        as_of=resolved.as_of,
        total=total,
        page=page,
        page_size=page_size,
        items=[run_out(run) for run in runs],
    )


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: int, session: Annotated[Session, Depends(get_db)]) -> RunOut:
    run = session.get(PipelineRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run_out(run)


BacklogStage = Literal["pending_summary", "abandoned_summary", "pending_embedding", "pending_score"]


class BacklogItem(BaseModel):
    id: int
    title: str
    source_id: str | None = None
    stage: BacklogStage
    failures: int | None = None


class BacklogCounts(BaseModel):
    pending_summaries: int
    abandoned_summaries: int
    pending_embeddings: int
    pending_scores: int


class BacklogOut(BaseModel):
    scope: Literal["current"] = "current"
    consistency: Literal["live"] = "live"
    publication_counts: dict[str, int] = {}
    counts: BacklogCounts
    stage: BacklogStage
    total: int
    page: int
    page_size: int
    items: list[BacklogItem]


@router.get("/backlog", response_model=BacklogOut)
def get_backlog(
    session: Annotated[Session, Depends(get_db)],
    stage: BacklogStage = "pending_summary",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> BacklogOut:
    article_conditions = {
        "pending_summary": pending_summary_conditions(),
        "abandoned_summary": abandoned_summary_conditions(),
        "pending_embedding": pending_embedding_conditions(),
    }
    counts = BacklogCounts(**backlog_counts(session))
    if stage == "pending_score":
        conditions = pending_score_conditions()
        total = counts.pending_scores
        rows = session.scalars(
            select(Event)
            .where(*conditions)
            .order_by(Event.changed_at.desc(), Event.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        items = [
            BacklogItem(id=row.id, title=row.title or f"Event #{row.id}", stage=stage)
            for row in rows
        ]
    else:
        conditions = article_conditions[stage]
        total = getattr(
            counts,
            {
                "pending_summary": "pending_summaries",
                "abandoned_summary": "abandoned_summaries",
                "pending_embedding": "pending_embeddings",
            }[stage],
        )
        articles = session.scalars(
            select(Article)
            .where(*conditions)
            .order_by(*summary_ordering())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        items = [
            BacklogItem(
                id=row.id,
                title=row.title,
                source_id=row.source_id,
                stage=stage,
                failures=row.summary_failures,
            )
            for row in articles
        ]
    return BacklogOut(
        publication_counts=publication_counts(session),
        counts=counts,
        stage=stage,
        total=total,
        page=page,
        page_size=page_size,
        items=items,
    )
