from collections.abc import Generator

import httpx
import pytest
from sqlalchemy.orm import Session

from unspun.api.app import app
from unspun.api.events import get_db
from unspun.core.models import FetchLog, LlmUsage


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
