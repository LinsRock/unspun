"""Idempotent deployment budget preflight never re-queries or changes a cutover."""

import sys
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from tests.test_billing import BillingDB
from unspun.core import billing_admin
from unspun.core.billing_models import BudgetCarry, BudgetPolicy
from unspun.core.config import get_settings

pytest_plugins = ["tests.test_billing"]


def snapshot(db: BillingDB) -> dict[str, Any]:
    with Session(db.engine) as session:
        policy = session.get(BudgetPolicy, 1)
        assert policy
        return {column.name: getattr(policy, column.name) for column in policy.__table__.columns}


@pytest.mark.parametrize("fault", [None, "key", "scope", "version", "incident", "observation"])
def test_existing_cutover_is_reused_or_rejected_without_network_or_writes(
    billing_db: BillingDB, monkeypatch: pytest.MonkeyPatch, fault: str | None
) -> None:
    db = billing_db
    identity = db.reserve()
    db.journal.unknown(identity, "synthetic unresolved cost")
    held = db.requests()[0].reserved_usd
    db.policy(scope="production", provider_observed_at=datetime.now(UTC))
    if fault == "key":
        monkeypatch.setenv("UNSPUN_OPENROUTER_API_KEY", "different-synthetic-key")
        get_settings.cache_clear()
    elif fault:
        db.policy(
            **{
                "scope": {"scope": "evaluation"},
                "version": {"version": "old-version"},
                "incident": {"incident": "preserved incident"},
                "observation": {"provider_observed_at": None},
            }[fault]
        )
    before = snapshot(db)

    def forbidden(_: httpx.Request) -> httpx.Response:
        raise AssertionError("initialized deployment must not query the provider")

    original = httpx.Client

    def client(**kwargs: Any) -> httpx.Client:
        return original(**kwargs, transport=httpx.MockTransport(forbidden))

    monkeypatch.setattr(billing_admin.httpx, "Client", client)
    monkeypatch.setattr(billing_admin, "get_engine", lambda: db.engine)
    monkeypatch.setattr(sys, "argv", ["billing_admin", "initialize-production"])
    if fault:
        with pytest.raises(ValueError, match="valid production budget cutover"):
            billing_admin.main()
    else:
        billing_admin.main()
    assert snapshot(db) == before
    assert db.requests()[0].status == "usage_unknown" and db.requests()[0].reserved_usd == held
    assert len(db.requests()) == 1 and not db.usage()


def test_first_production_initialization_still_requires_provider_observation(
    billing_db: BillingDB, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = billing_db
    # A genuine first cutover starts with neither policy nor an evaluation carry.
    with Session(db.engine) as session, session.begin():
        session.execute(delete(BudgetPolicy))
        session.execute(delete(BudgetCarry))
    calls: list[str] = []

    def observed(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(
            200, json={"data": {"usage": 0, "usage_monthly": 0, "limit": 100, "limit_reset": None}}
        )

    original = httpx.Client

    def client(**kwargs: Any) -> httpx.Client:
        return original(**kwargs, transport=httpx.MockTransport(observed))

    monkeypatch.setattr(billing_admin.httpx, "Client", client)
    monkeypatch.setattr(billing_admin, "get_engine", lambda: db.engine)
    monkeypatch.setattr(sys, "argv", ["billing_admin", "initialize-production"])
    billing_admin.main()
    assert len(calls) == 1 and calls[0].endswith("/key")
    after = snapshot(db)
    assert after["scope"] == "production" and after["provider_observed_at"]
