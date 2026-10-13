from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy.orm import Session

from unspun.api.admin.content import count_articles, count_events
from unspun.api.app import app
from unspun.api.events import get_db
from unspun.core.config import Settings, get_settings
from unspun.core.models import Article, Event, ExpenseEntry, FetchLog, LlmUsage, PipelineRun


@pytest.fixture
def overview_client(db_session: Session) -> Generator[httpx.AsyncClient]:
    def override_db() -> Generator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = lambda: Settings(admin_local_preview=True)
    yield httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1")
    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_overview_agrees_with_detail_queries_and_excludes_end(
    db_session: Session, overview_client: httpx.AsyncClient
) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    start = now - timedelta(days=1)
    source_id = f"overview-{now.timestamp()}"
    event = Event(title="Overview event", first_seen_at=start + timedelta(hours=2))
    db_session.add(event)
    db_session.flush()
    db_session.add_all(
        [
            Article(
                source_id=source_id,
                url=f"https://example.org/{source_id}-in",
                title="In",
                fetched_at=start + timedelta(hours=1),
                event_id=event.id,
            ),
            Article(
                source_id=source_id,
                url=f"https://example.org/{source_id}-out",
                title="Out",
                fetched_at=now,
                event_id=event.id,
            ),
            FetchLog(
                source_id=source_id,
                status="error",
                error="timeout",
                run_at=start + timedelta(hours=3),
            ),
            PipelineRun(run_at=start + timedelta(hours=4), new_events=1),
            LlmUsage(
                created_at=start + timedelta(hours=5),
                purpose="summary",
                model="test",
                cost_usd=0.125,
            ),
            ExpenseEntry(
                name="overview hosting",
                category="hosting",
                amount=10,
                currency="USD",
                kind="fixed",
                period_start=(start - timedelta(days=2)).date(),
                period_end=(now + timedelta(days=2)).date(),
                status="paid",
                paid_on=start.date(),
            ),
        ]
    )
    db_session.flush()
    params = {"start": start.isoformat(), "end": now.isoformat()}
    async with overview_client as client:
        overview = await client.get("/api/admin/overview", params=params)
        costs = await client.get("/api/admin/costs", params=params)
        runs = await client.get("/api/admin/runs", params=params)
        discovered = await client.get(
            "/api/admin/events", params={**params, "time_status": "discovered"}
        )
    assert overview.status_code == 200, overview.text
    body = overview.json()
    assert body["period"]["articles"] == count_articles(db_session, start, now)
    assert body["period"]["new_events"] >= 1
    assert discovered.status_code == 200
    assert body["period"]["new_events"] == count_events(
        db_session, start, now, time_status="discovered"
    )
    assert body["period"]["cost"]["total_confirmed_usd"] == costs.json()["total_confirmed_usd"]
    assert body["period"]["cost"]["calls"]["cost_usd"] == costs.json()["calls"]["cost_usd"]
    assert body["period"]["runs"] == runs.json()["total"]
    assert body["recent_run"]["status"] is None
    assert body["recent_run"]["missing_fields"]
    assert sum(point["articles"] for point in body["article_trend"]) == body["period"]["articles"]
    assert all(item["source_id"] != source_id for item in body["exceptions"]["sources"])
    assert body["current"]["scope"] == "current"
    assert body["granularity"] == "day"
    assert (
        sum(
            item["clustered"]
            + item["embedded"]
            + item["summarized"]
            + item["failed"]
            + item["pending"]
            for item in body["processing_trend"]
        )
        == body["period"]["articles"]
    )


@pytest.mark.anyio
async def test_overview_rejects_invalid_range(overview_client: httpx.AsyncClient) -> None:
    async with overview_client as client:
        result = await client.get(
            "/api/admin/overview",
            params={"start": "2026-10-12T00:00:00Z", "end": "2026-10-11T00:00:00Z"},
        )
    assert result.status_code == 422


@pytest.mark.anyio
async def test_overview_supports_hour_and_month_buckets(
    overview_client: httpx.AsyncClient,
) -> None:
    async with overview_client as client:
        hourly = await client.get(
            "/api/admin/overview",
            params={
                "start": "2026-10-12T16:00:00Z",
                "end": "2026-10-13T04:00:00Z",
                "granularity": "hour",
            },
        )
        monthly = await client.get(
            "/api/admin/overview",
            params={
                "start": "2024-12-31T16:00:00Z",
                "end": "2025-12-31T16:00:00Z",
                "granularity": "month",
            },
        )
    assert hourly.status_code == 200, hourly.text
    assert monthly.status_code == 200, monthly.text
    assert hourly.json()["granularity"] == "hour"
    assert len(hourly.json()["article_trend"]) == 12
    assert hourly.json()["article_trend"][0]["day"] == "2026-10-13 00:00"
    assert monthly.json()["granularity"] == "month"
    assert len(monthly.json()["article_trend"]) == 12
    assert monthly.json()["article_trend"][0]["day"] == "2025-01"
