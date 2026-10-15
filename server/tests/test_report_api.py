from collections.abc import Generator

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.reading_fixtures import approve
from unspun.api.app import app
from unspun.api.events import get_db
from unspun.core.models import Article, Event, FetchLog, LlmUsage, PipelineRun


@pytest.mark.anyio
async def test_daily_report_aggregates_failures_and_spend(db_session: Session) -> None:
    db_session.add_all(
        [
            FetchLog(source_id="report-ok", status="ok", new_articles=5),
            FetchLog(source_id="report-bad", status="error", error="HTTP 503"),
            FetchLog(source_id="report-bad", status="error", error="timeout"),
            LlmUsage(purpose="summary", model="m1", prompt_tokens=100, cost_usd=0.01),
            LlmUsage(purpose="summary", model="m1", prompt_tokens=200, cost_usd=0.02),
            LlmUsage(purpose="importance", model="m2", prompt_tokens=50, cost_usd=0.05),
        ]
    )
    db_session.flush()

    def override() -> Generator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = override
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/report/daily")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    failures = {f["source_id"]: f for f in body["source_failures"]}
    assert failures["report-bad"]["failures"] == 2
    spend = {(s["purpose"], s["model"]): s for s in body["llm_spend"]}
    assert spend[("summary", "m1")]["calls"] == 2
    assert spend[("summary", "m1")]["prompt_tokens"] == 300
    assert body["llm_cost_total_usd"] == pytest.approx(0.08)
    assert body["new_articles"] >= 5


@pytest.mark.anyio
async def test_daily_report_backlog_and_last_run(db_session: Session) -> None:
    event = Event(title="unscored event")
    db_session.add(event)
    db_session.add_all(
        [
            Article(
                source_id="backlog-src",
                url="https://example.com/backlog-pending",
                title="pending summary",
            ),
            Article(
                source_id="backlog-src",
                url="https://example.com/backlog-abandoned",
                title="abandoned article",
                summary_failures=3,
            ),
            Article(
                source_id="backlog-src",
                url="https://example.com/backlog-embed",
                title="pending embedding",
                summary_zh="summary present",
            ),
            PipelineRun(summarized=4, embedded=3, clustered=2, new_events=1, scored=5),
        ]
    )
    db_session.flush()

    for item in db_session.scalars(select(Article).where(Article.summary_zh == "summary present")):
        approve(item)
    db_session.flush()

    def override() -> Generator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = override
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/report/daily")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    backlog = body["backlog"]
    # >= guards against preexisting rows in a shared local database.
    assert backlog["pending_summaries"] >= 1
    assert backlog["pending_embeddings"] >= 1
    assert backlog["pending_scores"] >= 1
    assert backlog["abandoned_total"] >= 1
    abandoned = {a["id"]: a for a in backlog["abandoned_articles"]}
    abandoned_id = db_session.scalars(
        select(Article.id).where(Article.title == "abandoned article")
    ).one()
    assert abandoned[abandoned_id]["title"] == "abandoned article"
    assert abandoned[abandoned_id]["source_id"] == "backlog-src"
    last_run = body["last_run"]
    assert last_run is not None
    assert last_run["summarized"] == 4
    assert last_run["embedded"] == 3
    assert last_run["clustered"] == 2
    assert last_run["new_events"] == 1
    assert last_run["scored"] == 5
