from collections.abc import Generator

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from unspun.api.app import app
from unspun.api.events import get_db
from unspun.core.config import Settings, get_settings
from unspun.core.models import ExpenseAudit, ExpenseEntry


@pytest.mark.anyio
async def test_expense_write_denies_unverified_access() -> None:
    transport = httpx.ASGITransport(app=app, client=("198.51.100.5", 1234))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="https://admin.example",
        headers={"Origin": "https://admin.example"},
    ) as client:
        response = await client.post(
            "/api/admin/expense-rules",
            json={
                "name": "VPS",
                "category": "hosting",
                "amount": "10",
                "currency": "USD",
                "cadence": "monthly",
                "anchor_date": "2026-01-31",
                "reason": "invoice",
            },
        )
    assert response.status_code in {401, 503}


@pytest.fixture
def expense_client(db_session: Session) -> Generator[httpx.AsyncClient]:
    def override_db() -> Generator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = lambda: Settings(admin_local_preview=True)
    yield httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1",
        headers={"Origin": "http://127.0.0.1"},
    )
    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_rule_write_requires_identity_and_same_origin(
    expense_client: httpx.AsyncClient,
) -> None:
    payload = {
        "name": "VPS",
        "category": "hosting",
        "amount": "10",
        "currency": "USD",
        "cadence": "monthly",
        "anchor_date": "2026-01-31",
        "reason": "first bill",
    }
    async with expense_client as client:
        bad_origin = await client.post(
            "/api/admin/expense-rules", json=payload, headers={"Origin": "https://evil.example"}
        )
        good = await client.post("/api/admin/expense-rules", json=payload)
        stale = await client.patch(
            f"/api/admin/expense-rules/{good.json()['id']}",
            json={"version": 2, "amount": "12", "reason": "price change"},
        )
    assert bad_origin.status_code == 403
    assert good.status_code == 201
    assert good.json()["amount"] == "10"
    assert stale.status_code == 409


@pytest.mark.anyio
async def test_generate_payment_and_audit(
    expense_client: httpx.AsyncClient, db_session: Session
) -> None:
    async with expense_client as client:
        rule = await client.post(
            "/api/admin/expense-rules",
            json={
                "name": "VPS",
                "category": "hosting",
                "amount": "10",
                "currency": "USD",
                "cadence": "monthly",
                "anchor_date": "2026-01-31",
                "reason": "invoice",
            },
        )
        rule_id = rule.json()["id"]
        generated = await client.post(
            f"/api/admin/expense-rules/{rule_id}/generate", json={"through": "2026-03-01"}
        )
        repeated = await client.post(
            f"/api/admin/expense-rules/{rule_id}/generate", json={"through": "2026-03-01"}
        )
        entry_id = generated.json()["items"][0]["id"]
        paid = await client.patch(
            f"/api/admin/expenses/{entry_id}",
            json={"version": 1, "status": "paid", "paid_on": "2026-02-05", "reason": "receipt"},
        )
        stale = await client.patch(
            f"/api/admin/expenses/{entry_id}",
            json={"version": 1, "status": "paid", "paid_on": "2026-02-05", "reason": "repeat"},
        )
    assert generated.status_code == 200
    assert len(generated.json()["items"]) == 2
    assert repeated.json()["items"] == []
    assert paid.status_code == 200
    assert stale.status_code == 409
    entry = db_session.get(ExpenseEntry, entry_id)
    assert entry is not None and entry.status == "paid"
    audits = db_session.scalars(select(ExpenseAudit).order_by(ExpenseAudit.id)).all()
    assert [row.action for row in audits] == [
        "create_rule",
        "generate_entry",
        "generate_entry",
        "revise_entry",
    ]
    assert audits[-1].before is not None and audits[-1].before["status"] == "pending"
    assert audits[-1].after is not None and audits[-1].after["status"] == "paid"


@pytest.mark.anyio
async def test_invalid_amount_and_payment_precision_rejected(
    expense_client: httpx.AsyncClient,
) -> None:
    async with expense_client as client:
        invalid = await client.post(
            "/api/admin/expenses",
            json={
                "name": "Topup",
                "category": "models",
                "amount": "-1",
                "currency": "USD",
                "kind": "topup",
                "paid_on": "2026-01-01",
                "reason": "credit",
            },
        )
        missing_origin = await client.post(
            "/api/admin/expenses",
            json={
                "name": "Topup",
                "category": "models",
                "amount": "1",
                "currency": "USD",
                "kind": "topup",
                "paid_on": "2026-01-01",
                "reason": "credit",
            },
            headers={"Origin": ""},
        )
    assert invalid.status_code == 422
    assert missing_origin.status_code == 403


@pytest.mark.anyio
async def test_paid_correction_and_fx_rate_are_audited(
    expense_client: httpx.AsyncClient, db_session: Session
) -> None:
    async with expense_client as client:
        created = await client.post(
            "/api/admin/expenses",
            json={
                "name": "Domain",
                "category": "domain",
                "amount": "10",
                "currency": "CNY",
                "kind": "fixed",
                "period_start": "2026-01-01",
                "period_end": "2026-02-01",
                "paid_on": "2026-01-03",
                "reason": "invoice",
            },
        )
        entry_id = created.json()["id"]
        correction = await client.patch(
            f"/api/admin/expenses/{entry_id}/details",
            json={"version": 1, "amount": "12", "reason": "corrected invoice"},
        )
        rate = await client.put(
            "/api/admin/expense-rates",
            json={
                "currency": "CNY",
                "effective_on": "2026-01-01",
                "rate_to_usd": "0.14",
                "source": "manual statement",
                "reason": "statement rate",
            },
        )
        stale = await client.put(
            "/api/admin/expense-rates",
            json={
                "currency": "CNY",
                "effective_on": "2026-01-01",
                "rate_to_usd": "0.15",
                "source": "manual statement",
                "version": 2,
                "reason": "stale rate",
            },
        )
    assert created.status_code == 201
    assert correction.status_code == 200
    assert correction.json()["version"] == 2
    assert rate.status_code == 200
    assert stale.status_code == 409
    audits = db_session.scalars(select(ExpenseAudit).order_by(ExpenseAudit.id)).all()
    assert [row.action for row in audits] == ["create_entry", "correct_entry", "create_fx_rate"]


@pytest.mark.anyio
async def test_cost_api_preserves_decimal_precision_and_rejects_null_revision(
    expense_client: httpx.AsyncClient,
) -> None:
    async with expense_client as client:
        created = await client.post(
            "/api/admin/expenses",
            json={
                "name": "large invoice",
                "category": "hosting",
                "amount": "12345678901234.123456",
                "currency": "USD",
                "kind": "fixed",
                "period_start": "2026-01-01",
                "period_end": "2026-01-02",
                "reason": "bill",
            },
        )
        costs = await client.get(
            "/api/admin/expense-costs", params={"start": "2026-01-01", "end": "2026-01-02"}
        )
        invalid = await client.patch(
            f"/api/admin/expenses/{created.json()['id']}/details",
            json={"version": 1, "name": None, "reason": "invalid"},
        )
    assert costs.status_code == 200
    assert costs.json()["expected_by_currency"]["USD"] == "12345678901234.123456"
    assert costs.json()["expected_usd"] == "12345678901234.123456"
    assert invalid.status_code == 422
