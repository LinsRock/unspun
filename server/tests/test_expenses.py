from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from unspun.core.expense_allocation import allocate_days, period_for_index
from unspun.core.expenses import (
    ConflictError,
    correct_entry,
    cost_breakdown,
    create_entry,
    create_rule,
    generate_entries,
    payment_spend,
    revise_entry,
    revise_rule,
    set_fx_rate,
)
from unspun.core.models import ExpenseAudit, ExpenseEntry, LlmUsage


def test_month_end_anchor_survives_short_month() -> None:
    assert period_for_index(date(2025, 1, 31), "monthly", 1) == (
        date(2025, 2, 28),
        date(2025, 3, 31),
    )
    assert period_for_index(date(2024, 1, 31), "monthly", 1) == (
        date(2024, 2, 29),
        date(2024, 3, 31),
    )


def test_leap_day_yearly_anchor_recovers() -> None:
    assert period_for_index(date(2024, 2, 29), "yearly", 1) == (
        date(2025, 2, 28),
        date(2026, 2, 28),
    )
    assert period_for_index(date(2024, 2, 29), "yearly", 4)[0] == date(2028, 2, 29)


def test_partial_daily_allocation_reconciles_without_rounding_loss() -> None:
    coverage_start, coverage_end = date(2026, 1, 31), date(2026, 3, 31)
    amount = Decimal("19.99")
    first = allocate_days(amount, coverage_start, coverage_end, coverage_start, date(2026, 2, 28))
    second = allocate_days(amount, coverage_start, coverage_end, date(2026, 2, 28), coverage_end)
    assert first + second == amount
    assert allocate_days(amount, coverage_start, coverage_end, coverage_end, date(2026, 4, 1)) == 0


def test_daily_allocation_reconciles_repeating_fractions() -> None:
    days = [date(2026, 1, day) for day in range(1, 5)]
    parts = [
        allocate_days(Decimal("1"), days[0], days[3], days[index], days[index + 1])
        for index in range(3)
    ]
    assert sum(parts) == Decimal("1")
    assert parts[0] + allocate_days(Decimal("1"), days[0], days[3], days[1], days[3]) == Decimal(
        "1"
    )


def test_allocation_rejects_invalid_coverage() -> None:
    with pytest.raises(ValueError, match="coverage"):
        allocate_days(
            Decimal("1"), date(2026, 2, 1), date(2026, 2, 1), date(2026, 2, 1), date(2026, 2, 2)
        )


def test_rule_generation_is_idempotent_and_revisions_preserve_snapshots(
    db_session: Session,
) -> None:
    rule = create_rule(
        db_session,
        name="VPS",
        category="hosting",
        amount=Decimal("10"),
        currency="USD",
        cadence="monthly",
        anchor_date=date(2026, 1, 31),
        once_end=None,
        actor="owner",
        reason="initial subscription",
    )
    assert len(generate_entries(db_session, rule.id, date(2026, 4, 1), "owner")) == 3
    assert len(generate_entries(db_session, rule.id, date(2026, 4, 1), "owner")) == 0
    revise_rule(db_session, rule.id, 1, {"amount": Decimal("12")}, "owner", "price increase")
    assert len(generate_entries(db_session, rule.id, date(2026, 5, 1), "owner")) == 1
    entries = db_session.scalars(select(ExpenseEntry).order_by(ExpenseEntry.period_start)).all()
    assert [entry.amount for entry in entries] == [Decimal("10")] * 3 + [Decimal("12")]
    assert entries[1].period_start == date(2026, 2, 28)
    assert entries[2].period_start == date(2026, 3, 31)
    assert len(db_session.scalars(select(ExpenseAudit)).all()) == 6
    with pytest.raises(ConflictError):
        revise_rule(db_session, rule.id, 1, {"amount": Decimal("15")}, "owner", "stale")


def test_expected_becomes_confirmed_without_double_cost_and_topup_is_spend_only(
    db_session: Session,
) -> None:
    entry = create_entry(
        db_session,
        name="Domain",
        category="domain",
        amount=Decimal("36.50"),
        currency="USD",
        kind="fixed",
        period_start=date(2026, 1, 1),
        period_end=date(2027, 1, 1),
        actor="owner",
        reason="annual domain",
    )
    topup = create_entry(
        db_session,
        name="Model credit",
        category="models",
        amount=Decimal("20"),
        currency="USD",
        kind="topup",
        period_start=None,
        period_end=None,
        actor="owner",
        reason="credit purchase",
        paid_on=date(2026, 1, 5),
    )
    before = cost_breakdown(db_session, date(2026, 1, 1), date(2026, 2, 1))
    assert before.expected_by_currency["USD"] == Decimal("3.10")
    assert before.confirmed_by_currency == {}
    assert before.spend_by_currency == {"USD": Decimal("20")}
    revise_entry(
        db_session, entry.id, 1, "paid", "owner", "receipt received", paid_on=date(2026, 1, 8)
    )
    after = cost_breakdown(db_session, date(2026, 1, 1), date(2026, 2, 1))
    assert after.confirmed_by_currency["USD"] == Decimal("3.10")
    assert after.expected_by_currency == {}
    assert after.spend_by_currency == {"USD": Decimal("56.50")}
    assert db_session.get(ExpenseEntry, topup.id) is not None


def test_missing_rate_remains_unconverted(db_session: Session) -> None:
    create_entry(
        db_session,
        name="Server",
        category="hosting",
        amount=Decimal("31"),
        currency="CNY",
        kind="fixed",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 2, 1),
        actor="owner",
        reason="bill",
    )
    missing = cost_breakdown(db_session, date(2026, 1, 1), date(2026, 2, 1))
    assert missing.expected_by_currency == {"CNY": Decimal("31")}
    assert missing.expected_usd is None
    assert missing.unconverted_currencies == ["CNY"]
    set_fx_rate(
        db_session, "CNY", date(2026, 1, 1), Decimal("0.14"), "manual", "owner", "rate source"
    )
    converted = cost_breakdown(db_session, date(2026, 1, 1), date(2026, 2, 1))
    assert converted.expected_usd == Decimal("4.34")


def test_hourly_spend_keeps_date_only_payments_separate(db_session: Session) -> None:
    create_entry(
        db_session,
        name="dated",
        category="hosting",
        amount=Decimal("9"),
        currency="USD",
        kind="fixed",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 2, 1),
        paid_on=date(2026, 1, 5),
        actor="owner",
        reason="date-only receipt",
    )
    create_entry(
        db_session,
        name="timed",
        category="hosting",
        amount=Decimal("7"),
        currency="USD",
        kind="fixed",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 2, 1),
        paid_at=datetime(2026, 1, 5, 3, tzinfo=UTC),
        actor="owner",
        reason="timestamped receipt",
    )
    result = payment_spend(
        db_session, datetime(2026, 1, 5, 0, tzinfo=UTC), datetime(2026, 1, 5, 6, tzinfo=UTC)
    )
    assert result.exact_by_currency == {"USD": Decimal("7")}
    assert result.date_only_unplaced_by_currency == {"USD": Decimal("9")}


def test_naive_payment_timestamp_rejected(db_session: Session) -> None:
    with pytest.raises(ValueError, match="timezone"):
        create_entry(
            db_session,
            name="invalid",
            category="hosting",
            amount=Decimal("1"),
            currency="USD",
            kind="topup",
            period_start=None,
            period_end=None,
            paid_at=datetime(2026, 1, 1, 12),
            actor="owner",
            reason="receipt",
        )


def test_canceled_entry_cannot_gain_payment_date(db_session: Session) -> None:
    entry = create_entry(
        db_session,
        name="domain",
        category="domain",
        amount=Decimal("1"),
        currency="USD",
        kind="fixed",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 2, 1),
        actor="owner",
        reason="invoice",
    )
    with pytest.raises(ValueError, match="canceled"):
        revise_entry(db_session, entry.id, 1, "canceled", "owner", "void", paid_on=date(2026, 1, 2))
    with pytest.raises(ValueError, match="unpaid"):
        correct_entry(
            db_session, entry.id, 1, {"paid_on": date(2026, 1, 2)}, "owner", "invalid receipt"
        )


def test_llm_cost_uses_beijing_natural_day(db_session: Session) -> None:
    db_session.add(
        LlmUsage(
            created_at=datetime(2026, 1, 1, 17, tzinfo=UTC),
            purpose="summary",
            model="test",
            cost_usd=0.25,
        )
    )
    db_session.flush()
    today = cost_breakdown(db_session, date(2026, 1, 2), date(2026, 1, 3))
    assert today.llm_usd == Decimal("0.25")
    assert today.total_confirmed_usd == Decimal("0.25")
    assert cost_breakdown(db_session, date(2026, 1, 1), date(2026, 1, 2)).llm_usd == 0


def test_database_rejects_topup_with_service_coverage(db_session: Session) -> None:
    with pytest.raises(IntegrityError, match="ck_expense_entries_shape"), db_session.begin_nested():
        db_session.add(
            ExpenseEntry(
                name="invalid",
                category="models",
                amount=Decimal("1"),
                currency="USD",
                kind="topup",
                period_start=date(2026, 1, 1),
                period_end=date(2026, 2, 1),
                status="paid",
                paid_on=date(2026, 1, 1),
            )
        )
        db_session.flush()


def test_paid_entry_correction_keeps_prior_value_in_audit(db_session: Session) -> None:
    entry = create_entry(
        db_session,
        name="VPS",
        category="hosting",
        amount=Decimal("10"),
        currency="USD",
        kind="fixed",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 2, 1),
        paid_on=date(2026, 1, 5),
        actor="owner",
        reason="invoice",
    )
    corrected = correct_entry(
        db_session, entry.id, 1, {"amount": Decimal("12")}, "owner", "corrected receipt"
    )
    assert corrected.amount == Decimal("12")
    assert corrected.version == 2
    audit = db_session.scalars(select(ExpenseAudit).order_by(ExpenseAudit.id.desc())).first()
    assert audit is not None
    assert audit.before is not None and Decimal(audit.before["amount"]) == Decimal("10")
    assert audit.after is not None and audit.after["amount"] == "12.000000"
    with pytest.raises(ConflictError):
        correct_entry(db_session, entry.id, 1, {"amount": Decimal("14")}, "owner", "stale")


def test_rule_entry_period_cannot_be_corrected_into_duplicate(db_session: Session) -> None:
    rule = create_rule(
        db_session,
        name="VPS",
        category="hosting",
        amount=Decimal("10"),
        currency="USD",
        cadence="monthly",
        anchor_date=date(2026, 1, 1),
        once_end=None,
        actor="owner",
        reason="subscription",
    )
    entry = generate_entries(db_session, rule.id, date(2026, 2, 1), "owner")[0]
    with pytest.raises(ValueError, match="rule-generated coverage"):
        correct_entry(
            db_session, entry.id, 1, {"period_start": date(2026, 1, 2)}, "owner", "incorrect start"
        )
