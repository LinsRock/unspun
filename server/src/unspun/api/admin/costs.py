"""Cost history and LLM call drilldown from recorded usage and ledger entries."""

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, cast
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from unspun.api.admin.exports import EXPORT_LIMIT, csv_lines
from unspun.api.admin.query import Page, PageSize, RangeDep, page_result
from unspun.api.events import get_db
from unspun.core.billing import PRODUCTION_LIMIT, budget_status
from unspun.core.billing_models import BilledRequest
from unspun.core.expense_allocation import Cadence, allocate_days, period_for_index
from unspun.core.expenses import cost_breakdown, payment_spend
from unspun.core.models import ExpenseEntry, ExpenseRule, LlmUsage

router = APIRouter()
Db = Annotated[Session, Depends(get_db)]
BEIJING = ZoneInfo("Asia/Shanghai")


def _money(value: float | Decimal | int) -> Decimal:
    return Decimal(str(value))


def _calls(
    session: Session,
    start: datetime,
    end: datetime,
    model: str | None = None,
    purpose: str | None = None,
) -> list[LlmUsage]:
    query = select(LlmUsage).where(LlmUsage.created_at >= start, LlmUsage.created_at < end)
    if model:
        query = query.where(LlmUsage.model == model)
    if purpose:
        query = query.where(LlmUsage.purpose == purpose)
    return list(session.scalars(query.order_by(LlmUsage.created_at.desc(), LlmUsage.id.desc())))


def _rollup(rows: list[LlmUsage]) -> dict[str, object]:
    return {
        "count": len(rows),
        "unknown_token_calls": sum(
            row.prompt_tokens is None or row.completion_tokens is None for row in rows
        ),
        "prompt_tokens": sum(row.prompt_tokens or 0 for row in rows),
        "completion_tokens": sum(row.completion_tokens or 0 for row in rows),
        "cost_usd": sum((_money(row.cost_usd) for row in rows), Decimal(0)),
    }


def _call_row(row: LlmUsage, request: BilledRequest | None = None) -> dict[str, object]:
    return {
        "id": row.id,
        "created_at": row.created_at,
        "purpose": row.purpose,
        "model": row.model,
        "prompt_tokens": row.prompt_tokens,
        "completion_tokens": row.completion_tokens,
        "cost_usd": _money(row.cost_usd),
        "association": "recorded" if request else "not_recorded",
        "request_id": request.id if request else None,
        "task_id": request.task_id if request else None,
        "task_attempt_id": request.task_attempt_id if request else None,
        "article_id": request.article_id if request else None,
        "source_id": request.source_id if request else None,
        "stage": request.stage if request else None,
        "phase": request.phase if request else None,
    }


def _call_rows(session: Session, rows: list[LlmUsage]) -> list[dict[str, object]]:
    linked = {
        row.usage_id: row
        for row in session.scalars(
            select(BilledRequest).where(BilledRequest.usage_id.in_([item.id for item in rows]))
        )
    }
    return [_call_row(row, linked.get(row.id)) for row in rows]


def _coverage_days(period: RangeDep) -> tuple[date, date]:
    first = period.start.astimezone(BEIJING).date()
    last_at = period.end.astimezone(BEIJING)
    last = last_at.date() + (
        timedelta(days=1) if last_at.time().isoformat() != "00:00:00" else timedelta()
    )
    return first, last


def _fixed_entries(session: Session, period: RangeDep) -> list[dict[str, object]]:
    first, last = _coverage_days(period)
    entries = session.scalars(
        select(ExpenseEntry)
        .where(
            ExpenseEntry.kind == "fixed",
            ExpenseEntry.status != "canceled",
            ExpenseEntry.period_start < last,
            ExpenseEntry.period_end > first,
        )
        .order_by(ExpenseEntry.period_start.desc(), ExpenseEntry.id.desc())
    ).all()
    return [
        {
            "id": entry.id,
            "name": entry.name,
            "category": entry.category,
            "status": entry.status,
            "currency": entry.currency,
            "amount": entry.amount,
            "allocated": allocate_days(
                entry.amount,
                cast(date, entry.period_start),
                cast(date, entry.period_end),
                first,
                last,
            ),
            "period_start": entry.period_start,
            "period_end": entry.period_end,
        }
        for entry in entries
    ]


@router.get("/costs")
def get_costs(
    period: RangeDep, session: Db, model: str | None = None, purpose: str | None = None
) -> dict[str, object]:
    local_start, local_end = _coverage_days(period)
    fixed = cost_breakdown(session, local_start, local_end)
    day_based_spend = all(
        value.astimezone(BEIJING).time().isoformat() == "00:00:00"
        for value in (period.start, period.end)
    )
    unplaced = payment_spend(session, period.start, period.end)
    rows = _calls(session, period.start, period.end)
    selected = [
        row
        for row in rows
        if (not model or row.model == model) and (not purpose or row.purpose == purpose)
    ]
    trend: dict[date, Decimal] = defaultdict(Decimal)
    purposes: dict[str, Decimal] = defaultdict(Decimal)
    models: dict[str, Decimal] = defaultdict(Decimal)
    for row in rows:
        amount = _money(row.cost_usd)
        trend[row.created_at.astimezone(BEIJING).date()] += amount
        purposes[row.purpose] += amount
        models[row.model] += amount
    now_local = period.as_of.astimezone(BEIJING)
    month_start = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_spent = session.scalar(
        select(func.coalesce(func.sum(LlmUsage.cost_usd), 0)).where(
            LlmUsage.created_at >= month_start, LlmUsage.created_at < period.as_of
        )
    )
    call_cost = sum((_money(row.cost_usd) for row in rows), Decimal(0))
    confirmed_total = fixed.confirmed_usd + call_cost if fixed.confirmed_usd is not None else None
    covered_days = max(1, (local_end - local_start).days)
    return {
        "range": {
            "start": period.start,
            "end": period.end,
            "timezone": "Asia/Shanghai",
            "end_exclusive": True,
        },
        "as_of": period.as_of,
        "calls": _rollup(rows),
        "filtered_calls": _rollup(selected),
        "fixed": {
            "confirmed_by_currency": fixed.confirmed_by_currency,
            "expected_by_currency": fixed.expected_by_currency,
            "spend_by_currency": fixed.spend_by_currency if day_based_spend else {},
            "confirmed_usd": fixed.confirmed_usd,
            "expected_usd": fixed.expected_usd,
            "spend_usd": fixed.spend_usd if day_based_spend else None,
            "spend_precision": "day" if day_based_spend else "time_incomplete",
            "exact_spend_by_currency": unplaced.exact_by_currency,
            "date_only_unplaced_by_currency": unplaced.date_only_unplaced_by_currency,
            "unconverted_currencies": fixed.unconverted_currencies,
        },
        "total_confirmed_usd": confirmed_total,
        "covered_days": covered_days,
        "average_daily_usd": confirmed_total / covered_days
        if confirmed_total is not None
        else None,
        "trend": [{"day": day, "cost_usd": amount} for day, amount in sorted(trend.items())],
        "purposes": [
            {"name": name, "cost_usd": amount} for name, amount in sorted(purposes.items())
        ],
        "models": [{"name": name, "cost_usd": amount} for name, amount in sorted(models.items())],
        "budget": {
            "period": "current_month",
            "currency": "USD",
            "limit": PRODUCTION_LIMIT,
            "enforcement": budget_status(session),
            "spent": _money(month_spent or 0),
        },
        "fixed_day_basis": "overlapping_beijing_days",
    }


@router.get("/costs/entries/export.csv")
def export_fixed_entries(period: RangeDep, session: Db) -> StreamingResponse:
    rows = _fixed_entries(session, period)
    if len(rows) > EXPORT_LIMIT:
        raise HTTPException(
            status_code=422, detail="too many matching rows; choose narrower filters"
        )
    columns = [
        "id",
        "name",
        "category",
        "status",
        "currency",
        "amount",
        "allocated",
        "period_start",
        "period_end",
    ]
    return StreamingResponse(
        csv_lines(rows, columns),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="fixed-costs.csv"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/costs/entries")
def get_fixed_entries(
    period: RangeDep, session: Db, page: Page = 1, page_size: PageSize = 25
) -> dict[str, object]:
    rows = _fixed_entries(session, period)
    return page_result(
        rows[(page - 1) * page_size : page * page_size], period, page, page_size, total=len(rows)
    )


@router.get("/costs/calls/export.csv")
def export_calls(
    period: RangeDep, session: Db, model: str | None = None, purpose: str | None = None
) -> StreamingResponse:
    rows = _calls(session, period.start, period.end, model, purpose)
    if len(rows) > EXPORT_LIMIT:
        raise HTTPException(
            status_code=422, detail="too many matching rows; choose narrower filters"
        )
    columns = [
        "id",
        "created_at",
        "purpose",
        "model",
        "prompt_tokens",
        "completion_tokens",
        "cost_usd",
        "association",
    ]
    return StreamingResponse(
        csv_lines(_call_rows(session, rows), columns),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="llm-calls.csv"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/costs/calls")
def get_calls(
    period: RangeDep,
    session: Db,
    page: Page = 1,
    page_size: PageSize = 25,
    model: str | None = None,
    purpose: str | None = None,
) -> dict[str, object]:
    rows = _calls(session, period.start, period.end, model, purpose)
    return page_result(
        _call_rows(session, rows[(page - 1) * page_size : page * page_size]),
        period,
        page,
        page_size,
        total=len(rows),
    )


@router.get("/costs/requests")
def get_physical_requests(
    period: RangeDep, session: Db, page: Page = 1, page_size: PageSize = 25
) -> dict[str, object]:
    query = select(BilledRequest).where(
        BilledRequest.started_at >= period.start, BilledRequest.started_at < period.end
    )
    count = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.scalars(
        query.order_by(BilledRequest.started_at.desc(), BilledRequest.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = [
        {
            key: getattr(row, key)
            for key in (
                "id",
                "status",
                "purpose",
                "stage",
                "phase",
                "model",
                "task_id",
                "task_attempt_id",
                "article_id",
                "source_id",
                "usage_id",
                "reserved_usd",
                "provider_generation_id",
                "error",
                "started_at",
                "ended_at",
            )
        }
        for row in rows
    ]
    return page_result(items, period, page, page_size, total=count)


@router.get("/renewals")
def get_renewals(session: Db, days: Annotated[int, Query(ge=0, le=365)] = 7) -> dict[str, object]:
    today = datetime.now(BEIJING).date()
    rules = session.scalars(select(ExpenseRule).order_by(ExpenseRule.id)).all()
    items: list[dict[str, object]] = []
    pending = session.scalars(
        select(ExpenseEntry).where(
            ExpenseEntry.status == "pending",
            ExpenseEntry.period_start <= today + timedelta(days=365),
        )
    ).all()
    rules_by_id = {rule.id: rule for rule in rules}
    covered: set[tuple[int, date]] = set()
    for entry in pending:
        reminder = (
            rules_by_id[entry.rule_id].reminder_days if entry.rule_id in rules_by_id else days
        )
        if entry.period_start is None or entry.period_start > today + timedelta(days=reminder):
            continue
        if entry.rule_id is not None:
            covered.add((entry.rule_id, entry.period_start))
        items.append(
            {
                "entry_id": entry.id,
                "rule_id": entry.rule_id,
                "name": entry.name,
                "due_on": entry.period_start,
                "amount": entry.amount,
                "currency": entry.currency,
                "reminder_days": reminder,
                "overdue": entry.period_start < today,
            }
        )
    for rule in rules:
        if rule.stop_before is not None and rule.stop_before <= today:
            continue
        for index in range(121):
            if rule.cadence == "once" and index > 0:
                break
            start, _ = period_for_index(
                rule.anchor_date, cast(Cadence, rule.cadence), index, rule.once_end
            )
            if start >= today:
                if (
                    start <= today + timedelta(days=rule.reminder_days)
                    and (rule.id, start) not in covered
                ) and (rule.stop_before is None or start < rule.stop_before):
                    items.append(
                        {
                            "rule_id": rule.id,
                            "name": rule.name,
                            "due_on": start,
                            "amount": rule.amount,
                            "currency": rule.currency,
                            "reminder_days": rule.reminder_days,
                            "overdue": False,
                        }
                    )
                break
    return {
        "scope": "current",
        "items": sorted(
            items,
            key=lambda item: (cast(date, item["due_on"]), cast(int | None, item["rule_id"]) or 0),
        ),
    }
