import pytest

from unspun.evaluation.run_quality import BudgetExceeded, BudgetLedger


def test_budget_stops_future_calls_after_reported_spend_reaches_cap() -> None:
    ledger = BudgetLedger(0.01, 10)
    ledger.reserve()
    ledger.charge(0.01, 1)
    with pytest.raises(BudgetExceeded):
        ledger.reserve()


def test_call_cap_prevents_unbounded_retries() -> None:
    ledger = BudgetLedger(1.0, 1)
    ledger.reserve()
    with pytest.raises(BudgetExceeded):
        ledger.reserve()


def test_usage_retry_requests_and_cost_are_recorded() -> None:
    ledger = BudgetLedger(1.0, 10)
    ledger.reserve()
    ledger.charge(0.012, 2)
    assert ledger.cost_usd == pytest.approx(0.012)
    assert ledger.calls == 2
