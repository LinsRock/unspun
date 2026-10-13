"""Transactional expense ledger operations shared by admin APIs."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, cast
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from unspun.core.expense_allocation import Cadence, allocate_days, period_for_index
from unspun.core.models import ExpenseAudit, ExpenseEntry, ExpenseRule, FxRate, LlmUsage

BEIJING = ZoneInfo("Asia/Shanghai")


class ConflictError(ValueError):
    pass


def _snapshot(row: ExpenseRule | ExpenseEntry | FxRate) -> dict[str, Any]:
    return {
        column.name: str(getattr(row, column.name))
        if isinstance(getattr(row, column.name), (Decimal, date, datetime))
        else getattr(row, column.name)
        for column in row.__table__.columns
    }


def _audit(
    session: Session,
    actor: str,
    action: str,
    row: ExpenseRule | ExpenseEntry | FxRate,
    before: dict[str, Any] | None,
    reason: str,
) -> None:
    session.add(
        ExpenseAudit(
            actor=actor,
            action=action,
            object_type=row.__tablename__,
            object_id=row.id,
            before=before,
            after=_snapshot(row),
            reason=reason,
        )
    )


def create_rule(
    session: Session,
    *,
    name: str,
    category: str,
    amount: Decimal,
    currency: str,
    cadence: Cadence,
    anchor_date: date,
    once_end: date | None,
    actor: str,
    reason: str,
    reminder_days: int = 7,
) -> ExpenseRule:
    if cadence == "once" and (once_end is None or once_end <= anchor_date):
        raise ValueError("one-time rule requires coverage end")
    if cadence != "once" and once_end is not None:
        raise ValueError("recurring rule cannot have one-time end")
    row = ExpenseRule(
        name=name,
        category=category,
        amount=amount,
        currency=currency,
        cadence=cadence,
        anchor_date=anchor_date,
        once_end=once_end,
        reminder_days=reminder_days,
    )
    session.add(row)
    session.flush()
    _audit(session, actor, "create_rule", row, None, reason)
    return row


def revise_rule(
    session: Session, rule_id: int, version: int, changes: dict[str, Any], actor: str, reason: str
) -> ExpenseRule:
    row = session.get(ExpenseRule, rule_id)
    if row is None:
        raise LookupError("rule not found")
    before = _snapshot(row)
    allowed = {"name", "category", "amount", "currency", "stop_before", "reminder_days"}
    if not changes or not changes.keys() <= allowed:
        raise ValueError("unsupported rule change")
    if any(changes.get(key) is None for key in changes.keys() - {"stop_before"}):
        raise ValueError("required rule field cannot be null")
    updated = session.scalar(
        update(ExpenseRule)
        .where(ExpenseRule.id == rule_id, ExpenseRule.version == version)
        .values(**changes, version=version + 1)
        .returning(ExpenseRule.id)
    )
    if updated is None:
        raise ConflictError("rule version changed")
    session.refresh(row)
    _audit(session, actor, "revise_rule", row, before, reason)
    return row


def generate_entries(
    session: Session, rule_id: int, through: date, actor: str
) -> list[ExpenseEntry]:
    rule = session.scalar(select(ExpenseRule).where(ExpenseRule.id == rule_id).with_for_update())
    if rule is None:
        raise LookupError("rule not found")
    if through <= rule.anchor_date:
        return []
    if (through - rule.anchor_date).days > 3660:
        raise ValueError("generation horizon exceeds ten years")
    existing = set(
        session.scalars(
            select(ExpenseEntry.period_start).where(ExpenseEntry.rule_id == rule_id)
        ).all()
    )
    created: list[ExpenseEntry] = []
    for index in range(121):
        if rule.cadence == "once" and index > 0:
            break
        start, end = period_for_index(
            rule.anchor_date, cast(Cadence, rule.cadence), index, rule.once_end
        )
        if start >= through or (rule.stop_before is not None and start >= rule.stop_before):
            break
        if start not in existing:
            inserted = session.scalar(
                pg_insert(ExpenseEntry)
                .values(
                    rule_id=rule.id,
                    rule_version=rule.version,
                    name=rule.name,
                    category=rule.category,
                    amount=rule.amount,
                    currency=rule.currency,
                    kind="fixed",
                    period_start=start,
                    period_end=end,
                    status="pending",
                )
                .on_conflict_do_nothing(constraint="uq_expense_entries_rule_period")
                .returning(ExpenseEntry.id)
            )
            if inserted is not None:
                entry = session.get(ExpenseEntry, inserted)
                assert entry is not None
                _audit(session, actor, "generate_entry", entry, None, "periodic rule")
                created.append(entry)
    return created


def create_entry(
    session: Session,
    *,
    name: str,
    category: str,
    amount: Decimal,
    currency: str,
    kind: str,
    period_start: date | None,
    period_end: date | None,
    actor: str,
    reason: str,
    paid_on: date | None = None,
    paid_at: datetime | None = None,
) -> ExpenseEntry:
    if kind == "fixed" and (
        period_start is None or period_end is None or period_end <= period_start
    ):
        raise ValueError("fixed expense requires valid coverage")
    if kind == "topup" and (period_start is not None or period_end is not None):
        raise ValueError("topup cannot have service coverage")
    if paid_on is not None and paid_at is not None:
        raise ValueError("provide payment date or timestamp")
    if paid_at is not None and (paid_at.tzinfo is None or paid_at.utcoffset() is None):
        raise ValueError("payment timestamp requires a timezone")
    if kind == "topup" and paid_on is None and paid_at is None:
        raise ValueError("topup requires payment date")
    row = ExpenseEntry(
        name=name,
        category=category,
        amount=amount,
        currency=currency,
        kind=kind,
        period_start=period_start,
        period_end=period_end,
        status="paid" if paid_on or paid_at else "pending",
        paid_on=paid_on,
        paid_at=paid_at,
    )
    session.add(row)
    session.flush()
    _audit(session, actor, "create_entry", row, None, reason)
    return row


def revise_entry(
    session: Session,
    entry_id: int,
    version: int,
    status: str,
    actor: str,
    reason: str,
    *,
    paid_on: date | None = None,
    paid_at: datetime | None = None,
) -> ExpenseEntry:
    row = session.get(ExpenseEntry, entry_id)
    if row is None:
        raise LookupError("entry not found")
    if row.version != version:
        raise ConflictError("entry version changed")
    if status == "paid" and not (paid_on or paid_at) or paid_on and paid_at:
        raise ValueError("payment needs one date or timestamp")
    if status == "canceled" and (paid_on is not None or paid_at is not None):
        raise ValueError("canceled entry cannot have payment date")
    if paid_at is not None and (paid_at.tzinfo is None or paid_at.utcoffset() is None):
        raise ValueError("payment timestamp requires a timezone")
    if status == "canceled" and row.status == "paid":
        raise ValueError("paid entry cannot be canceled")
    if status not in {"paid", "canceled"} or row.status != "pending":
        raise ValueError("entry cannot make this transition")
    before = _snapshot(row)
    updated = session.scalar(
        update(ExpenseEntry)
        .where(ExpenseEntry.id == entry_id, ExpenseEntry.version == version)
        .values(status=status, paid_on=paid_on, paid_at=paid_at, version=version + 1)
        .returning(ExpenseEntry.id)
    )
    if updated is None:
        raise ConflictError("entry version changed")
    session.refresh(row)
    _audit(session, actor, "revise_entry", row, before, reason)
    return row


def correct_entry(
    session: Session, entry_id: int, version: int, changes: dict[str, Any], actor: str, reason: str
) -> ExpenseEntry:
    row = session.get(ExpenseEntry, entry_id)
    if row is None:
        raise LookupError("entry not found")
    if row.version != version:
        raise ConflictError("entry version changed")
    allowed = {
        "name",
        "category",
        "amount",
        "currency",
        "period_start",
        "period_end",
        "paid_on",
        "paid_at",
    }
    if not changes or not changes.keys() <= allowed:
        raise ValueError("unsupported entry correction")
    if any(
        changes.get(key) is None
        for key in changes.keys() & {"name", "category", "amount", "currency"}
    ):
        raise ValueError("required entry field cannot be null")
    if row.rule_id is not None and {"period_start", "period_end"} & changes.keys():
        raise ValueError("rule-generated coverage cannot be corrected")
    data = {key: getattr(row, key) for key in allowed}
    data.update(changes)
    if row.kind == "fixed" and (
        data["period_start"] is None
        or data["period_end"] is None
        or data["period_end"] <= data["period_start"]
    ):
        raise ValueError("fixed expense requires valid coverage")
    if row.kind == "topup" and (data["period_start"] is not None or data["period_end"] is not None):
        raise ValueError("topup cannot have service coverage")
    if data["paid_on"] is not None and data["paid_at"] is not None:
        raise ValueError("provide payment date or timestamp")
    if row.status == "paid" and data["paid_on"] is None and data["paid_at"] is None:
        raise ValueError("paid entry requires payment date")
    if row.status != "paid" and (data["paid_on"] is not None or data["paid_at"] is not None):
        raise ValueError("unpaid entry cannot have payment date")
    paid_at = data["paid_at"]
    if paid_at is not None and (paid_at.tzinfo is None or paid_at.utcoffset() is None):
        raise ValueError("payment timestamp requires a timezone")
    before = _snapshot(row)
    updated = session.scalar(
        update(ExpenseEntry)
        .where(ExpenseEntry.id == entry_id, ExpenseEntry.version == version)
        .values(**changes, version=version + 1)
        .returning(ExpenseEntry.id)
    )
    if updated is None:
        raise ConflictError("entry version changed")
    session.refresh(row)
    _audit(session, actor, "correct_entry", row, before, reason)
    return row


def set_fx_rate(
    session: Session,
    currency: str,
    effective_on: date,
    rate_to_usd: Decimal,
    source: str,
    actor: str,
    reason: str,
    version: int | None = None,
) -> FxRate:
    row = session.scalar(
        select(FxRate).where(FxRate.currency == currency, FxRate.effective_on == effective_on)
    )
    if row is None:
        if version is not None:
            raise ConflictError("rate does not exist")
        row = FxRate(
            currency=currency, effective_on=effective_on, rate_to_usd=rate_to_usd, source=source
        )
        session.add(row)
        session.flush()
        _audit(session, actor, "create_fx_rate", row, None, reason)
        return row
    if version is None:
        raise ConflictError("rate already exists")
    before = _snapshot(row)
    updated = session.scalar(
        update(FxRate)
        .where(FxRate.id == row.id, FxRate.version == version)
        .values(rate_to_usd=rate_to_usd, source=source, version=version + 1)
        .returning(FxRate.id)
    )
    if updated is None:
        raise ConflictError("rate version changed")
    session.refresh(row)
    _audit(session, actor, "revise_fx_rate", row, before, reason)
    return row


@dataclass
class CostBreakdown:
    confirmed_by_currency: dict[str, Decimal] = field(default_factory=lambda: {})
    expected_by_currency: dict[str, Decimal] = field(default_factory=lambda: {})
    spend_by_currency: dict[str, Decimal] = field(default_factory=lambda: {})
    confirmed_usd: Decimal | None = Decimal(0)
    expected_usd: Decimal | None = Decimal(0)
    spend_usd: Decimal | None = Decimal(0)
    unconverted_currencies: list[str] = field(default_factory=lambda: [])
    llm_usd: Decimal = Decimal(0)

    @property
    def total_confirmed_usd(self) -> Decimal | None:
        return None if self.confirmed_usd is None else self.confirmed_usd + self.llm_usd


@dataclass
class PaymentSpend:
    exact_by_currency: dict[str, Decimal] = field(default_factory=lambda: {})
    date_only_unplaced_by_currency: dict[str, Decimal] = field(default_factory=lambda: {})


def payment_spend(session: Session, start: datetime, end: datetime) -> PaymentSpend:
    if any(value.tzinfo is None or value.utcoffset() is None for value in (start, end)):
        raise ValueError("spend range requires a timezone")
    if end <= start:
        raise ValueError("spend range must be positive")
    result = PaymentSpend()
    for entry in session.scalars(select(ExpenseEntry).where(ExpenseEntry.status == "paid")):
        if entry.paid_at is not None and start <= entry.paid_at < end:
            bucket = result.exact_by_currency
        elif entry.paid_on is not None:
            day_start = datetime.combine(entry.paid_on, time.min, BEIJING)
            if day_start >= end or day_start + timedelta(days=1) <= start:
                continue
            bucket = result.date_only_unplaced_by_currency
        else:
            continue
        bucket[entry.currency] = bucket.get(entry.currency, Decimal(0)) + entry.amount
    return result


def _rate(rates: Sequence[FxRate], currency: str, day: date) -> Decimal | None:
    if currency == "USD":
        return Decimal(1)
    applicable = [row for row in rates if row.currency == currency and row.effective_on <= day]
    return max(applicable, key=lambda row: row.effective_on).rate_to_usd if applicable else None


def cost_breakdown(session: Session, start: date, end: date) -> CostBreakdown:
    if end <= start:
        raise ValueError("cost range must be positive")
    result = CostBreakdown()
    rates = session.scalars(select(FxRate)).all()
    entries = session.scalars(select(ExpenseEntry).where(ExpenseEntry.status != "canceled")).all()
    missing: set[str] = set()

    def add(
        bucket: dict[str, Decimal], usd_name: str, currency: str, amount: Decimal, day: date
    ) -> None:
        bucket[currency] = bucket.get(currency, Decimal(0)) + amount
        rate = _rate(rates, currency, day)
        if rate is None:
            missing.add(currency)
            setattr(result, usd_name, None)
        elif getattr(result, usd_name) is not None:
            setattr(result, usd_name, getattr(result, usd_name) + amount * rate)

    for entry in entries:
        if entry.kind == "fixed" and entry.period_start and entry.period_end:
            day = max(start, entry.period_start)
            while day < min(end, entry.period_end):
                portion = allocate_days(
                    entry.amount,
                    entry.period_start,
                    entry.period_end,
                    day,
                    date.fromordinal(day.toordinal() + 1),
                )
                bucket = (
                    result.confirmed_by_currency
                    if entry.status == "paid"
                    else result.expected_by_currency
                )
                usd_name = "confirmed_usd" if entry.status == "paid" else "expected_usd"
                add(bucket, usd_name, entry.currency, portion, day)
                day = date.fromordinal(day.toordinal() + 1)
        payment_day = entry.paid_on or (
            entry.paid_at.astimezone(BEIJING).date() if entry.paid_at else None
        )
        if entry.status == "paid" and payment_day and start <= payment_day < end:
            add(result.spend_by_currency, "spend_usd", entry.currency, entry.amount, payment_day)
    start_at = datetime.combine(start, time.min, BEIJING).astimezone(UTC)
    end_at = datetime.combine(end, time.min, BEIJING).astimezone(UTC)
    usages = session.scalars(
        select(LlmUsage).where(LlmUsage.created_at >= start_at, LlmUsage.created_at < end_at)
    ).all()
    for usage in usages:
        if start <= usage.created_at.astimezone(BEIJING).date() < end:
            result.llm_usd += Decimal(str(usage.cost_usd))
    result.unconverted_currencies = sorted(missing)
    return result
