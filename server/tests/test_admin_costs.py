from collections.abc import Generator
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy.orm import Session

from unspun.api.app import app
from unspun.api.events import get_db
from unspun.core.config import Settings, get_settings
from unspun.core.models import ExpenseEntry, ExpenseRule, LlmUsage


@pytest.fixture
def costs_client(db_session: Session) -> Generator[httpx.AsyncClient]:
    def override_db() -> Generator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = lambda: Settings(admin_local_preview=True)
    yield httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1")
    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_cost_totals_filters_and_calls_agree(
    costs_client: httpx.AsyncClient, db_session: Session
) -> None:
    db_session.add_all(
        [
            LlmUsage(
                created_at=datetime(2026, 10, 10, 1, tzinfo=UTC),
                purpose="summary",
                model="a",
                prompt_tokens=10,
                completion_tokens=2,
                cost_usd=0.125,
            ),
            LlmUsage(
                created_at=datetime(2026, 10, 10, 2, tzinfo=UTC),
                purpose="embedding",
                model="b",
                prompt_tokens=4,
                completion_tokens=0,
                cost_usd=0.000001,
            ),
            ExpenseEntry(
                name="VPS",
                category="hosting",
                amount=10,
                currency="USD",
                kind="fixed",
                period_start=datetime(2026, 10, 10).date(),
                period_end=datetime(2026, 10, 11).date(),
                status="paid",
                paid_on=datetime(2026, 10, 10).date(),
            ),
        ]
    )
    db_session.flush()
    params = {"start": "2026-10-09T16:00:00Z", "end": "2026-10-10T16:00:00Z"}
    async with costs_client as client:
        summary = await client.get("/api/admin/costs", params=params)
        filtered = await client.get("/api/admin/costs", params={**params, "model": "a"})
        calls = await client.get("/api/admin/costs/calls", params=params)
        fixed = await client.get("/api/admin/costs/entries", params=params)
    assert summary.status_code == 200, summary.text
    assert calls.status_code == 200, calls.text
    assert summary.json()["calls"]["count"] == 2
    assert summary.json()["calls"]["cost_usd"] == "0.125001"
    assert filtered.json()["filtered_calls"]["cost_usd"] == "0.125"
    assert filtered.json()["fixed"]["confirmed_usd"] == "10.000000"
    assert sum(float(row["cost_usd"]) for row in calls.json()["items"]) == pytest.approx(0.125001)
    assert all(row["association"] == "not_recorded" for row in calls.json()["items"])
    assert fixed.status_code == 200
    assert (
        fixed.json()["items"][0]["allocated"]
        == summary.json()["fixed"]["confirmed_by_currency"]["USD"]
    )


@pytest.mark.anyio
async def test_cost_calls_csv_and_invalid_range(
    costs_client: httpx.AsyncClient, db_session: Session
) -> None:
    db_session.add(
        LlmUsage(
            created_at=datetime(2026, 10, 10, 1, tzinfo=UTC),
            purpose="=unsafe",
            model="a",
            cost_usd=0.01,
        )
    )
    db_session.flush()
    params = {"start": "2026-10-09T16:00:00Z", "end": "2026-10-10T16:00:00Z"}
    async with costs_client as client:
        csv = await client.get("/api/admin/costs/calls/export.csv", params=params)
        invalid = await client.get(
            "/api/admin/costs", params={"start": params["end"], "end": params["start"]}
        )
    assert csv.status_code == 200
    assert "'=unsafe" in csv.text
    assert invalid.status_code == 422


@pytest.mark.anyio
async def test_rolling_range_does_not_assign_date_only_payment_to_an_hour(
    costs_client: httpx.AsyncClient, db_session: Session
) -> None:
    from datetime import date

    db_session.add(
        ExpenseEntry(
            name="Hosting",
            category="hosting",
            amount=8,
            currency="USD",
            kind="fixed",
            period_start=date(2026, 10, 10),
            period_end=date(2026, 10, 11),
            status="paid",
            paid_on=date(2026, 10, 10),
        )
    )
    db_session.flush()
    async with costs_client as client:
        result = await client.get(
            "/api/admin/costs",
            params={"start": "2026-10-10T00:00:00Z", "end": "2026-10-10T08:00:00Z"},
        )
    assert result.status_code == 200
    assert result.json()["fixed"]["spend_usd"] is None
    assert result.json()["fixed"]["date_only_unplaced_by_currency"] == {"USD": "8.000000"}


@pytest.mark.anyio
async def test_renewals_sort_manual_entries_and_respect_rule_reminder(
    costs_client: httpx.AsyncClient, db_session: Session
) -> None:
    from datetime import timedelta
    from zoneinfo import ZoneInfo

    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    db_session.add_all(
        [
            ExpenseEntry(
                name="Manual",
                category="hosting",
                amount=2,
                currency="USD",
                kind="fixed",
                period_start=today,
                period_end=today + timedelta(days=1),
                status="pending",
            ),
            ExpenseRule(
                name="Today",
                category="hosting",
                amount=3,
                currency="USD",
                cadence="once",
                anchor_date=today,
                once_end=today + timedelta(days=1),
                reminder_days=0,
            ),
            ExpenseRule(
                name="Tomorrow",
                category="hosting",
                amount=4,
                currency="USD",
                cadence="once",
                anchor_date=today + timedelta(days=1),
                once_end=today + timedelta(days=2),
                reminder_days=0,
            ),
        ]
    )
    db_session.flush()
    async with costs_client as client:
        response = await client.get("/api/admin/renewals")
    assert response.status_code == 200
    assert {item["name"] for item in response.json()["items"]} == {"Manual", "Today"}
