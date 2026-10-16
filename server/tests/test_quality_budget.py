from decimal import Decimal

import pytest

from unspun.evaluation.run_quality import BudgetExceeded, BudgetLedger


def test_conservative_reservation_stops_before_physical_request() -> None:
    ledger = BudgetLedger(0.01, 10)
    with pytest.raises(BudgetExceeded):
        ledger.reserve(Decimal("0.011"))
    assert ledger.calls == 0


def test_call_cap_prevents_unbounded_retries() -> None:
    ledger = BudgetLedger(0.6, 1)
    ledger.reserve(Decimal("0.03"))
    ledger.settle(Decimal("0.03"), Decimal("0.001"))
    with pytest.raises(BudgetExceeded):
        ledger.reserve(Decimal("0.03"))


def test_known_charge_releases_hold_but_unknown_still_occupies_it() -> None:
    ledger = BudgetLedger(0.1, 10)
    ledger.reserve(Decimal("0.08"))
    with pytest.raises(BudgetExceeded):
        ledger.reserve(Decimal("0.03"))
    ledger.settle(Decimal("0.08"), Decimal("0.012"))
    ledger.reserve(Decimal("0.08"))
    assert ledger.cost_usd == pytest.approx(0.012)
    assert ledger.calls == 2


def test_failed_shared_reservation_is_not_a_physical_call() -> None:
    ledger = BudgetLedger(0.1, 10)
    ledger.reserve(Decimal("0.08"))
    ledger.cancel(Decimal("0.08"))
    assert ledger.calls == 0
    ledger.reserve(Decimal("0.1"))
