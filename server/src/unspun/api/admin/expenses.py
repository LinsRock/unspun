"""Authenticated, same-origin expense ledger APIs."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from unspun.api.admin.auth import require_admin_identity
from unspun.api.events import get_db
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
from unspun.core.models import ExpenseEntry, ExpenseRule, FxRate

router = APIRouter()
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
Money = Annotated[Decimal, Field(gt=0, max_digits=20, decimal_places=6)]
Reason = Annotated[str, Field(min_length=1, max_length=500)]


def same_origin(request: Request) -> None:
    origin = request.headers.get("origin", "")
    parsed = urlsplit(origin)
    host = request.headers.get("host", "")
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.netloc != host
        or parsed.path
        or parsed.query
    ):
        raise HTTPException(status_code=403, detail="Same-origin request required")
    if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise HTTPException(status_code=403, detail="HTTPS origin required")


Write = Annotated[None, Depends(same_origin)]
Db = Annotated[Session, Depends(get_db)]
Actor = Annotated[str, Depends(require_admin_identity)]


def translate_error(error: Exception) -> HTTPException:
    if isinstance(error, (ConflictError, IntegrityError)):
        return HTTPException(status_code=409, detail="Expense version or unique key conflict")
    if isinstance(error, LookupError):
        return HTTPException(status_code=404, detail=str(error))
    return HTTPException(status_code=422, detail=str(error))


class RuleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, Field(min_length=1, max_length=200)]
    category: Annotated[str, Field(min_length=1, max_length=80)]
    amount: Money
    currency: Currency
    cadence: Literal["once", "monthly", "yearly"]
    anchor_date: date
    once_end: date | None = None
    reminder_days: Annotated[int, Field(ge=0, le=365)] = 7
    reason: Reason


class RuleRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Annotated[int, Field(ge=1)]
    reason: Reason
    name: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    category: Annotated[str, Field(min_length=1, max_length=80)] | None = None
    amount: Money | None = None
    currency: Currency | None = None
    stop_before: date | None = None
    reminder_days: Annotated[int, Field(ge=0, le=365)] | None = None


class GenerateRequest(BaseModel):
    through: date


class EntryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, Field(min_length=1, max_length=200)]
    category: Annotated[str, Field(min_length=1, max_length=80)]
    amount: Money
    currency: Currency
    kind: Literal["fixed", "topup"]
    period_start: date | None = None
    period_end: date | None = None
    paid_on: date | None = None
    paid_at: datetime | None = None
    reason: Reason


class EntryRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Annotated[int, Field(ge=1)]
    status: Literal["paid", "canceled"]
    paid_on: date | None = None
    paid_at: datetime | None = None
    reason: Reason


class EntryCorrection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Annotated[int, Field(ge=1)]
    reason: Reason
    name: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    category: Annotated[str, Field(min_length=1, max_length=80)] | None = None
    amount: Money | None = None
    currency: Currency | None = None
    period_start: date | None = None
    period_end: date | None = None
    paid_on: date | None = None
    paid_at: datetime | None = None


class RateWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    currency: Currency
    effective_on: date
    rate_to_usd: Annotated[Decimal, Field(gt=0, max_digits=24, decimal_places=12)]
    source: Annotated[str, Field(min_length=1, max_length=200)]
    version: int | None = None
    reason: Reason

    @field_validator("currency")
    @classmethod
    def non_usd(cls, value: str) -> str:
        if value == "USD":
            raise ValueError("USD does not need a rate")
        return value


class RuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    category: str
    amount: Decimal
    currency: str
    cadence: str
    anchor_date: date
    once_end: date | None
    stop_before: date | None
    reminder_days: int
    version: int


class EntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    rule_id: int | None
    rule_version: int | None
    name: str
    category: str
    amount: Decimal
    currency: str
    kind: str
    period_start: date | None
    period_end: date | None
    status: str
    paid_on: date | None
    paid_at: datetime | None
    version: int


class RateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    currency: str
    effective_on: date
    rate_to_usd: Decimal
    source: str
    version: int


class CostOut(BaseModel):
    start: date
    end: date
    confirmed_by_currency: dict[str, Decimal]
    expected_by_currency: dict[str, Decimal]
    spend_by_currency: dict[str, Decimal]
    confirmed_usd: Decimal | None
    expected_usd: Decimal | None
    spend_usd: Decimal | None
    unconverted_currencies: list[str]
    llm_usd: Decimal
    total_confirmed_usd: Decimal | None


class SpendOut(BaseModel):
    start: datetime
    end: datetime
    exact_by_currency: dict[str, Decimal]
    date_only_unplaced_by_currency: dict[str, Decimal]


@router.post("/expense-rules", response_model=RuleOut, status_code=201)
def post_rule(body: RuleCreate, _: Write, session: Db, actor: Actor) -> ExpenseRule:
    try:
        return create_rule(
            session, **body.model_dump(exclude={"reason"}), actor=actor, reason=body.reason
        )
    except (ValueError, IntegrityError) as error:
        raise translate_error(error) from error


@router.patch("/expense-rules/{rule_id}", response_model=RuleOut)
def patch_rule(
    rule_id: int, body: RuleRevision, _: Write, session: Db, actor: Actor
) -> ExpenseRule:
    changes = body.model_dump(exclude={"version", "reason"}, exclude_unset=True)
    try:
        return revise_rule(session, rule_id, body.version, changes, actor, body.reason)
    except (ValueError, LookupError, IntegrityError) as error:
        raise translate_error(error) from error


@router.post("/expense-rules/{rule_id}/generate")
def post_generate(
    rule_id: int, body: GenerateRequest, _: Write, session: Db, actor: Actor
) -> dict[str, list[EntryOut]]:
    try:
        return {
            "items": [
                EntryOut.model_validate(row)
                for row in generate_entries(session, rule_id, body.through, actor)
            ]
        }
    except (ValueError, LookupError, IntegrityError) as error:
        raise translate_error(error) from error


@router.post("/expenses", response_model=EntryOut, status_code=201)
def post_entry(body: EntryCreate, _: Write, session: Db, actor: Actor) -> ExpenseEntry:
    try:
        return create_entry(
            session, **body.model_dump(exclude={"reason"}), actor=actor, reason=body.reason
        )
    except (ValueError, IntegrityError) as error:
        raise translate_error(error) from error


@router.patch("/expenses/{entry_id}", response_model=EntryOut)
def patch_entry(
    entry_id: int, body: EntryRevision, _: Write, session: Db, actor: Actor
) -> ExpenseEntry:
    try:
        return revise_entry(
            session,
            entry_id,
            body.version,
            body.status,
            actor,
            body.reason,
            paid_on=body.paid_on,
            paid_at=body.paid_at,
        )
    except (ValueError, LookupError, IntegrityError) as error:
        raise translate_error(error) from error


@router.patch("/expenses/{entry_id}/details", response_model=EntryOut)
def patch_entry_details(
    entry_id: int, body: EntryCorrection, _: Write, session: Db, actor: Actor
) -> ExpenseEntry:
    changes = body.model_dump(exclude={"version", "reason"}, exclude_unset=True)
    try:
        return correct_entry(session, entry_id, body.version, changes, actor, body.reason)
    except (ValueError, LookupError, IntegrityError) as error:
        raise translate_error(error) from error


@router.put("/expense-rates", response_model=RateOut)
def put_rate(body: RateWrite, _: Write, session: Db, actor: Actor) -> FxRate:
    try:
        return set_fx_rate(
            session,
            body.currency,
            body.effective_on,
            body.rate_to_usd,
            body.source,
            actor,
            body.reason,
            body.version,
        )
    except (ValueError, IntegrityError) as error:
        raise translate_error(error) from error


@router.get("/expense-rules", response_model=list[RuleOut])
def get_rules(session: Db) -> list[ExpenseRule]:
    return list(session.scalars(select(ExpenseRule).order_by(ExpenseRule.id)))


@router.get("/expenses", response_model=list[EntryOut])
def get_entries(
    session: Db,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[ExpenseEntry]:
    return list(
        session.scalars(
            select(ExpenseEntry)
            .order_by(ExpenseEntry.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )


@router.get("/expense-rates", response_model=list[RateOut])
def get_rates(session: Db) -> list[FxRate]:
    return list(
        session.scalars(select(FxRate).order_by(FxRate.currency, FxRate.effective_on.desc()))
    )


@router.get("/expense-costs", response_model=CostOut)
def get_costs(start: date, end: date, session: Db) -> CostOut:
    try:
        costs = cost_breakdown(session, start, end)
    except ValueError as error:
        raise translate_error(error) from error
    return CostOut(
        start=start, end=end, total_confirmed_usd=costs.total_confirmed_usd, **vars(costs)
    )


@router.get("/expense-spend", response_model=SpendOut)
def get_spend(start: datetime, end: datetime, session: Db) -> SpendOut:
    try:
        spend = payment_spend(session, start, end)
    except ValueError as error:
        raise translate_error(error) from error
    return SpendOut(start=start, end=end, **vars(spend))
