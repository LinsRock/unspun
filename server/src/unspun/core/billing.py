"""Atomic shared budgets and independent physical-call accounting.

Never expires an unresolved reservation or invents a zero provider fee. Business
transactions cannot roll back requests or usage already committed here.
"""

import copy
import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from typing import Any, Literal, Protocol, cast

from sqlalchemy import Engine, case, func, insert, select
from sqlalchemy.orm import Session

from unspun.core.billing_models import BilledRequest, BudgetCarry, BudgetPolicy
from unspun.core.config import get_settings
from unspun.core.content import fingerprint
from unspun.core.content_costs import content_unit_costs
from unspun.core.llm import LlmError
from unspun.core.models import LlmUsage
from unspun.core.task_models import PipelineTask, TaskAttempt
from unspun.core.tasks import Lease

POLICY_VERSION = "r1-budget-v3"
PRICE_VERSION = "openrouter-text-2026-10-16-v1"
MONTHLY_LIMIT = Decimal("15.00")
EVALUATION_LIMIT = Decimal("1.50")
PRODUCTION_LIMIT = MONTHLY_LIMIT - EVALUATION_LIMIT
STAGE_CAPS = {"legacy": str(PRODUCTION_LIMIT), "card": "10", "guide": "2", "embedding": "1"}
TOPIC_STAGE_CAPS = {
    "topic_embedding": "0.10",
    "topic_judgment": "0.45",
    "topic_review": "0.45",
}
Stage = Literal[
    "legacy", "card", "guide", "embedding", "topic_embedding", "topic_judgment", "topic_review"
]
PENDING = ("reserved", "usage_unknown")
PRICES = {
    "google/gemini-2.5-flash-lite": (Decimal("0.10"), Decimal("0.40")),
    "google/gemini-2.5-flash": (Decimal("0.30"), Decimal("2.50")),
    "qwen/qwen3-embedding-8b": (Decimal("0.01"), Decimal("0")),
}


class BudgetExceeded(LlmError):
    def __init__(self, reason: str, retry_at: datetime | None = None) -> None:
        super().__init__(reason)
        self.retry_at = retry_at or datetime.now(UTC) + timedelta(minutes=5)


class UsageUnknown(BudgetExceeded):
    pass


@dataclass(frozen=True)
class CallContext:
    stage: Stage = "legacy"
    phase: str | None = None
    logical_key: str | None = None
    lease: Lease | None = None


@dataclass(frozen=True)
class Reservation:
    id: str
    response: dict[str, Any] | None = None


class CallJournal(Protocol):
    def reserve(
        self, *, purpose: str, model: str, request: dict[str, Any], context: CallContext
    ) -> Reservation: ...
    def identify(self, identity: str, generation_id: str, http_status: int) -> None: ...
    def finish(self, identity: str, data: dict[str, Any], http_status: int) -> bool: ...
    def unknown(self, identity: str, reason: str, http_status: int | None = None) -> None: ...


def usd(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() and result >= 0 else None


def token_count(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def month_start(now: datetime) -> datetime:
    return now.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def next_month(now: datetime) -> datetime:
    start = month_start(now)
    return (
        start.replace(year=start.year + 1, month=1)
        if start.month == 12
        else start.replace(month=start.month + 1)
    )


def provider_cap(model: str) -> dict[str, Any]:
    if model not in PRICES:
        raise BudgetExceeded("model has no registered price bound")
    prompt, completion = PRICES[model]
    return {"max_price": {"prompt": float(prompt), "completion": float(completion), "request": 0}}


def reservation_bound(model: str, request: dict[str, Any]) -> Decimal:
    provider_cap(model)
    if model == "qwen/qwen3-embedding-8b":
        inputs = request.get("input", [])
        if not isinstance(inputs, list) or any(
            not isinstance(v, str) for v in cast(list[Any], inputs)
        ):
            raise LlmError("embedding inputs must be strings")
        byte_count = sum(len(v.encode()) for v in cast(list[str], inputs))
        if byte_count > 32768:
            raise LlmError("embedding batch exceeds the registered input bound")
        return max(
            Decimal("0.001"), Decimal(byte_count + 512) * Decimal("0.00000001") + Decimal("0.0005")
        )
    messages = request.get("messages", [])
    byte_count = sum(len(str(v["content"]).encode()) for v in messages)
    if byte_count > 262144 or not 1 <= request.get("max_tokens", 0) <= 65535:
        raise LlmError("chat input/output exceeds registered bounds")
    prompt, completion = PRICES[model]
    # Use the published full output window, including reasoning, plus slack;
    # do not assume that excluded reasoning is free or only bill visible text.
    reserve = (
        (Decimal(byte_count + 512) * (prompt + Decimal("0.083334"))) + Decimal(66559) * completion
    ) / Decimal(1_000_000) + Decimal("0.001")
    return reserve.quantize(Decimal("0.000001"), rounding=ROUND_CEILING)


def _known(session: Session, since: datetime, stage: str | None = None) -> Decimal:
    query = select(func.coalesce(func.sum(LlmUsage.cost_usd), 0))
    if stage is not None:
        query = query.outerjoin(BilledRequest, BilledRequest.usage_id == LlmUsage.id).where(
            case(
                (BilledRequest.id.is_not(None), BilledRequest.stage),
                (LlmUsage.purpose == "embedding", "embedding"),
                else_="legacy",
            )
            == stage
        )
    return Decimal(str(session.scalar(query.where(LlmUsage.created_at >= since)) or 0))


def initialize_budget(
    session: Session,
    *,
    scope: Literal["production", "evaluation"],
    provider_monthly_usd: Decimal | None = None,
    provider_usage_usd: Decimal | None = None,
    provider_limit_usd: Decimal | None = None,
    provider_limit_kind: Literal["lifetime", "monthly"] = "lifetime",
    now: datetime | None = None,
) -> None:
    now = now or datetime.now(UTC)
    if not get_settings().openrouter_api_key:
        raise LlmError("billing initialization requires the configured provider key")
    policy = session.scalar(select(BudgetPolicy).where(BudgetPolicy.id == 1).with_for_update())
    if policy is not None and policy.enabled:
        if policy.scope != scope:
            raise LlmError("active billing scope cannot be changed")
        return
    if policy is not None and policy.incident:
        raise BudgetExceeded("billing incident remains paused pending reviewed reconciliation")
    known = _known(session, month_start(now))
    if scope == "production" and (
        provider_monthly_usd is None or usd(provider_monthly_usd) is None
    ):
        raise BudgetExceeded("production cutover requires observed provider monthly usage")
    if scope == "evaluation" and known != 0:
        raise BudgetExceeded("evaluation must start with an empty isolated usage ledger")
    if policy is None:
        policy = BudgetPolicy(id=1)
        session.add(policy)
    policy.scope, policy.version = scope, POLICY_VERSION
    policy.monthly_limit_usd = PRODUCTION_LIMIT if scope == "production" else EVALUATION_LIMIT
    policy.stage_caps = STAGE_CAPS if scope == "production" else {}
    policy.coverage_started_at, policy.enabled, policy.incident = now, True, None
    if scope == "production":
        if provider_usage_usd is None or usd(provider_usage_usd) is None:
            raise BudgetExceeded("production cutover requires observed provider total usage")
        policy.provider_limit_usd = provider_limit_usd
        policy.provider_usage_usd = (
            provider_monthly_usd if provider_limit_kind == "monthly" else provider_usage_usd
        )
        policy.provider_limit_kind = provider_limit_kind
        policy.provider_observed_at = now
    policy.key_fingerprint = hashlib.sha256(get_settings().openrouter_api_key.encode()).hexdigest()
    carry = (
        max(Decimal(0), (provider_monthly_usd or Decimal(0)) - known)
        if scope == "production"
        else Decimal(0)
    )
    session.add(
        BudgetCarry(
            month=month_start(now).date(),
            amount_usd=carry,
            provider_monthly_usd=provider_monthly_usd,
            ledger_at_observation_usd=known,
            basis="provider-cutover" if scope == "production" else "isolated-evaluation-allocation",
            observed_at=now,
        )
    )


class DatabaseJournal:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def reserve(
        self, *, purpose: str, model: str, request: dict[str, Any], context: CallContext
    ) -> Reservation:
        amount = reservation_bound(model, request)
        now = datetime.now(UTC)
        stage = (
            "embedding"
            if purpose == "embedding" and context.stage not in TOPIC_STAGE_CAPS
            else context.stage
        )
        logical = (
            fingerprint([context.logical_key, context.phase, purpose, model, request])
            if context.logical_key
            else None
        )
        with Session(self.engine) as session, session.begin():
            policy = session.scalar(
                select(BudgetPolicy).where(BudgetPolicy.id == 1).with_for_update()
            )
            if policy is None or not policy.enabled or policy.coverage_started_at is None:
                raise BudgetExceeded("billing is not initialized or is paused")
            if (
                policy.key_fingerprint
                != hashlib.sha256(get_settings().openrouter_api_key.encode()).hexdigest()
            ):
                raise BudgetExceeded(
                    "provider key changed; a reviewed accounting cutover is required"
                )
            lease = context.lease
            topic_kind = lease is not None and lease.kind in {
                "topic_recall",
                "topic_judge",
                "topic_review",
            }
            if topic_kind or stage in TOPIC_STAGE_CAPS or purpose == "topic_judgment":
                if not get_settings().r2_member_processing_enabled:
                    raise BudgetExceeded("member processing is disabled")
                expected = {
                    "topic_embedding": ("topic_recall", "embed", "embedding"),
                    "topic_judgment": ("topic_judge", "judge", "topic_judgment"),
                    "topic_review": ("topic_review", "review", "grounding"),
                }.get(stage)
                if (
                    lease is None
                    or lease.article_id is None
                    or lease.queue != "paid"
                    or expected != (lease.kind, context.phase, purpose)
                    or lease.strategy_version != "r2-member-v1"
                    or not context.logical_key
                    or model
                    != {
                        "topic_embedding": get_settings().embedding_model,
                        "topic_judgment": get_settings().summary_model,
                        "topic_review": get_settings().viewpoint_model,
                    }.get(stage)
                ):
                    raise LlmError("member work requires its registered task, stage and phase")
                allocations = {k: usd(v) for k, v in policy.stage_caps.items()}
                cap = allocations.get(stage)
                if cap is None or cap <= 0:
                    raise BudgetExceeded("member stage has no explicit allocation")
                if policy.scope == "production" and (
                    any(v is None for v in allocations.values())
                    or allocations.get("legacy") != 0
                    or any(k not in STAGE_CAPS and k not in TOPIC_STAGE_CAPS for k in allocations)
                    or sum((v for v in allocations.values() if v is not None), Decimal(0))
                    > min(policy.monthly_limit_usd, PRODUCTION_LIMIT)
                ):
                    raise BudgetExceeded(
                        "member allocations must fit the original production total"
                    )
            if (
                policy.scope == "production"
                and stage in ("card", "guide")
                and (lease is None or lease.article_id is None)
            ):
                raise LlmError("production R1 paid work requires a persisted content task lease")
            if lease is not None:
                active = session.scalar(
                    select(PipelineTask.id).where(
                        PipelineTask.id == lease.task_id,
                        PipelineTask.object_key == lease.object_key,
                        PipelineTask.article_id == lease.article_id,
                        PipelineTask.kind == lease.kind,
                        PipelineTask.queue == lease.queue,
                        PipelineTask.input_fingerprint == lease.input_fingerprint,
                        PipelineTask.strategy_version == lease.strategy_version,
                        TaskAttempt.id == lease.attempt_id,
                        TaskAttempt.task_id == PipelineTask.id,
                        TaskAttempt.claim_version == lease.version,
                        TaskAttempt.status == "running",
                        PipelineTask.status == "running",
                        PipelineTask.claim_version == lease.version,
                        PipelineTask.claimed_by == lease.worker,
                        PipelineTask.lease_until > now,
                    )
                )
                if active is None:
                    raise LlmError("stale task lease cannot initiate a paid request")
            if logical is not None:
                previous = session.scalar(
                    select(BilledRequest).where(BilledRequest.logical_key == logical)
                )
                if previous is not None:
                    if previous.status == "responded" and previous.response_payload is not None:
                        return Reservation(previous.id, copy.deepcopy(previous.response_payload))
                    raise UsageUnknown("previous physical request awaits reconciliation")
            if lease is not None:
                unresolved = session.scalar(
                    select(BilledRequest.id)
                    .where(
                        BilledRequest.object_key == lease.object_key,
                        BilledRequest.status.in_(PENDING),
                    )
                    .limit(1)
                )
                if unresolved is not None:
                    raise UsageUnknown("canonical object has an unresolved request")
            start = month_start(now)
            carry = session.get(BudgetCarry, start.date())
            if carry is None:
                if policy.coverage_started_at >= start:
                    raise BudgetExceeded("monthly accounting anchor is missing")
                carry = BudgetCarry(
                    month=start.date(),
                    amount_usd=Decimal(0),
                    ledger_at_observation_usd=Decimal(0),
                    basis="continuous-accounting-since-cutover",
                    observed_at=now,
                )
                session.add(carry)
            pending = Decimal(
                str(
                    session.scalar(
                        select(func.coalesce(func.sum(BilledRequest.reserved_usd), 0)).where(
                            BilledRequest.status.in_(PENDING)
                        )
                    )
                    or 0
                )
            )
            if policy.scope == "production" and policy.provider_limit_usd is not None:
                if policy.provider_usage_usd is None:
                    raise BudgetExceeded("provider usage anchor is unknown")
                # Reserve the evaluation allocation inside the existing key cap.
                ceiling = max(Decimal(0), policy.provider_limit_usd - EVALUATION_LIMIT)
                baseline = policy.provider_usage_usd
                since = policy.coverage_started_at
                if policy.provider_limit_kind == "monthly" and since < start:
                    baseline, since = Decimal(0), start
                if baseline + _known(session, since) + pending + amount > ceiling:
                    raise BudgetExceeded(
                        "existing provider key limit including reservations exhausted"
                    )
            limit = min(
                policy.monthly_limit_usd,
                PRODUCTION_LIMIT if policy.scope == "production" else EVALUATION_LIMIT,
            )
            spent_since = policy.coverage_started_at if policy.scope == "evaluation" else start
            if _known(session, spent_since) + carry.amount_usd + pending + amount > limit:
                raise BudgetExceeded(
                    "monthly budget including reservations exhausted", next_month(now)
                )
            if policy.scope == "production" or stage in TOPIC_STAGE_CAPS:
                cap = min(
                    Decimal(str(policy.stage_caps.get(stage, "0"))),
                    Decimal({**STAGE_CAPS, **TOPIC_STAGE_CAPS}[stage]),
                )
                stage_pending = Decimal(
                    str(
                        session.scalar(
                            select(func.coalesce(func.sum(BilledRequest.reserved_usd), 0)).where(
                                BilledRequest.status.in_(PENDING), BilledRequest.stage == stage
                            )
                        )
                        or 0
                    )
                )
                if _known(session, start, stage) + stage_pending + amount > cap:
                    raise BudgetExceeded(
                        "stage budget including reservations exhausted", next_month(now)
                    )
            if purpose == "grounding":
                since = now - timedelta(hours=24)
                spent = Decimal(
                    str(
                        session.scalar(
                            select(func.coalesce(func.sum(LlmUsage.cost_usd), 0)).where(
                                LlmUsage.purpose == "grounding", LlmUsage.created_at >= since
                            )
                        )
                        or 0
                    )
                )
                held = Decimal(
                    str(
                        session.scalar(
                            select(func.coalesce(func.sum(BilledRequest.reserved_usd), 0)).where(
                                BilledRequest.purpose == "grounding",
                                BilledRequest.status.in_(PENDING),
                            )
                        )
                        or 0
                    )
                )
                # An explicitly configured isolated evaluation increase still
                # fits its single cumulative allocation. Production keeps the
                # original independent review ceiling even with a larger setting.
                ceiling = EVALUATION_LIMIT if policy.scope == "evaluation" else Decimal("0.40")
                cap = min(ceiling, Decimal(str(get_settings().grounding_budget_24h_usd)))
                if spent + held + amount > cap:
                    raise BudgetExceeded(
                        "rolling grounding budget including reservations exhausted"
                    )
            row = BilledRequest(
                id=uuid.uuid4().hex,
                logical_key=logical,
                purpose=purpose,
                stage=stage,
                phase=context.phase or purpose,
                model=model,
                request_fingerprint=fingerprint(request),
                price_version=PRICE_VERSION,
                reserved_usd=amount,
                status="reserved",
                started_at=now,
                task_id=lease.task_id if lease else None,
                task_attempt_id=lease.attempt_id if lease else None,
                article_id=lease.article_id if lease else None,
                source_id=lease.source_id if lease else None,
                object_key=lease.object_key if lease else None,
            )
            session.add(row)
            session.flush()
            return Reservation(row.id)

    def identify(self, identity: str, generation_id: str, http_status: int) -> None:
        """Persist a provider response header before reading its fallible body."""
        if not generation_id or len(generation_id) > 256:
            raise LlmError("invalid provider generation identifier")
        with Session(self.engine) as session, session.begin():
            session.scalar(select(BudgetPolicy).where(BudgetPolicy.id == 1).with_for_update())
            row = session.get(BilledRequest, identity, with_for_update=True)
            if row is None:
                raise LlmError("physical request reservation is missing")
            if row.provider_generation_id not in (None, generation_id):
                raise LlmError("provider generation identifier changed")
            other = session.scalar(
                select(BilledRequest.id).where(
                    BilledRequest.provider_generation_id == generation_id,
                    BilledRequest.id != identity,
                )
            )
            if other is not None:
                raise LlmError("provider generation identifier belongs to another request")
            row.provider_generation_id, row.http_status = generation_id, http_status

    def finish(self, identity: str, data: dict[str, Any], http_status: int) -> bool:
        return self._finish(identity, data, http_status, response_received=True)

    def _finish(
        self, identity: str, data: dict[str, Any], http_status: int, *, response_received: bool
    ) -> bool:
        overrun = False
        with Session(self.engine) as session, session.begin():
            policy = session.scalar(
                select(BudgetPolicy).where(BudgetPolicy.id == 1).with_for_update()
            )
            row = session.get(BilledRequest, identity, with_for_update=True)
            if row is None:
                raise LlmError("physical request reservation is missing")
            if row.usage_id is not None:
                return row.status == "responded"
            raw_usage = data.get("usage")
            usage = cast(dict[str, Any], raw_usage) if isinstance(raw_usage, dict) else {}
            cost = usd(usage.get("cost"))
            row.http_status, row.response_payload, row.usage_payload = http_status, data, usage
            generation_id = data.get("id")
            if isinstance(generation_id, str):
                if row.provider_generation_id not in (None, generation_id):
                    raise LlmError("provider response identifier does not match its header")
                row.provider_generation_id = generation_id
            row.ended_at = datetime.now(UTC)
            if cost is None:
                row.status, row.error = "usage_unknown", "provider cost missing or invalid"
                return False
            row.usage_id = session.scalar(
                insert(LlmUsage)
                .values(
                    purpose=row.purpose,
                    model=row.model,
                    prompt_tokens=token_count(usage.get("prompt_tokens")),
                    completion_tokens=0
                    if row.purpose == "embedding"
                    else token_count(usage.get("completion_tokens")),
                    cost_usd=float(cost),
                    created_at=row.ended_at,
                )
                .returning(LlmUsage.id)
            )
            row.status = (
                "responded"
                if response_received and 200 <= http_status < 300
                else "settled_without_result"
            )
            if row.status == "settled_without_result":
                row.logical_key = None
            overrun = cost > row.reserved_usd
            if overrun and policy is not None:
                policy.enabled, policy.incident = False, f"reservation exceeded: {row.id}"
        if overrun:
            raise BudgetExceeded("actual provider cost exceeded reservation; billing paused")
        return True

    def unknown(self, identity: str, reason: str, http_status: int | None = None) -> None:
        with Session(self.engine) as session, session.begin():
            row = session.get(BilledRequest, identity, with_for_update=True)
            if row is not None and row.usage_id is None:
                row.status, row.error = "usage_unknown", reason[:1000]
                if http_status is not None:
                    row.http_status = http_status
                row.ended_at = datetime.now(UTC)

    def reconcile(self, identity: str, evidence: dict[str, Any]) -> bool:
        """Settle only an identified generation; never infer a free timeout.

        The caller obtains this object from the authenticated, read-only
        provider generation endpoint. Keep it separate from the original reply.
        """
        with Session(self.engine) as session, session.begin():
            row = session.get(BilledRequest, identity, with_for_update=True)
            if row is None or row.provider_generation_id is None:
                raise UsageUnknown("request has no provider generation identifier")
            if evidence.get("id") != row.provider_generation_id:
                raise LlmError("generation evidence does not match the request")
            cost = usd(evidence.get("total_cost"))
            if cost is None:
                raise UsageUnknown("provider reconciliation has no confirmed cost")
            original_response = copy.deepcopy(
                row.reconciliation.get("original_response", row.response_payload)
                if row.reconciliation is not None
                else row.response_payload
            )
            original = copy.deepcopy(original_response or {})
            response_received = original_response is not None
            original["id"] = row.provider_generation_id
            original["usage"] = {
                "cost": str(cost),
                "prompt_tokens": token_count(evidence.get("native_tokens_prompt")),
                "completion_tokens": token_count(evidence.get("native_tokens_completion")),
            }
            status = row.http_status or 0
            row.reconciliation = {
                **(row.reconciliation or {}),
                "provider": evidence,
                "original_response": original_response,
                "observed_at": datetime.now(UTC).isoformat(),
            }
        # finish() serializes with reservations and is idempotent. An interruption
        # between these commits leaves the hold intact and can safely be retried.
        return self._finish(identity, original, status, response_received=response_received)


def budget_status(session: Session) -> dict[str, Any]:
    """Known cost is distinct from unresolved holds and historical coverage."""
    policy = session.get(BudgetPolicy, 1)
    rows = list(session.scalars(select(BilledRequest).where(BilledRequest.status.in_(PENDING))))
    held = sum((row.reserved_usd for row in rows), Decimal(0))
    start = month_start(datetime.now(UTC))
    carry = session.get(BudgetCarry, start.date())
    since = (
        policy.coverage_started_at
        if policy and policy.scope == "evaluation"
        else start
        if policy
        else None
    )
    known = _known(session, since) if since is not None else None
    carry_amount = carry.amount_usd if carry else None
    carry_basis = carry.basis if carry else None
    if (
        carry is None
        and policy
        and policy.coverage_started_at
        and policy.coverage_started_at < start
    ):
        # reserve() creates this same zero anchor for a fully covered new month.
        # The status endpoint derives it without writing or resetting any holds.
        carry_amount, carry_basis = Decimal(0), "continuous-accounting-since-cutover"
    occupancy = (
        known + carry_amount + held if known is not None and carry_amount is not None else None
    )
    return {
        "enabled": bool(policy and policy.enabled),
        "scope": policy.scope if policy else None,
        "monthly_limit_usd": str(policy.monthly_limit_usd) if policy else None,
        "evaluation_allocation_usd": str(EVALUATION_LIMIT),
        "stage_caps": policy.stage_caps if policy else {},
        "coverage_started_at": policy.coverage_started_at if policy else None,
        "incident": policy.incident if policy else None,
        "unresolved_calls": len(rows),
        "reserved_usd": str(held),
        "accounting": {
            "period": "since_cutover" if policy and policy.scope == "evaluation" else "utc_month",
            "known_spend_usd": str(known) if known is not None else None,
            "historical_carry_usd": str(carry_amount) if carry_amount is not None else None,
            "carry_basis": carry_basis,
            "unresolved_holds_usd": str(held),
            "occupancy_usd": str(occupancy) if occupancy is not None else None,
            "holds_are_not_actual_fees": True,
        },
        "provider_limit_usd": str(policy.provider_limit_usd)
        if policy and policy.provider_limit_usd is not None
        else None,
        "provider_observed_at": policy.provider_observed_at if policy else None,
        "cost_basis": "llm_usage_known_fees_only",
        "unit_costs": content_unit_costs(session),
    }
