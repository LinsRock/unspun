"""Measured runtime cohorts; frozen evaluation calls keep their separate denominators."""

from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from unspun.core.billing_models import BilledRequest
from unspun.core.models import Article, ContentDerivation, LlmUsage
from unspun.core.task_models import PipelineTask


def _known(value: float | None) -> Decimal | None:
    amount = Decimal(str(value)) if value is not None else None
    return amount if amount is not None and amount.is_finite() and amount >= 0 else None


def _metric(cohort: dict[str, Any], count: int, denominator: str, scale: int = 1) -> dict[str, Any]:
    known = cohort["known_cost_usd"]
    unknown = cohort["unknown_requests"]
    value = Decimal(known) * scale / count if count and known is not None else None
    upper = (
        ((Decimal(known) if known is not None else Decimal(0)) + Decimal(cohort["held_usd"]))
        * scale
        / count
        if count and not cohort["unknown_without_hold"]
        else None
    )
    status = (
        "unmeasured"
        if not count
        else "unknown"
        if known is None
        else "known_lower_bound"
        if unknown
        else "measured"
    )
    return {
        "status": status,
        "denominator": denominator,
        "denominator_count": count,
        "value_usd": str(value) if value is not None else None,
        "known_plus_holds_scenario_usd": str(upper) if upper is not None else None,
        "holds_are_not_actual_fees": True,
    }


def _cohort(session: Session, kind: Literal["card", "guide"], version: str) -> dict[str, Any]:
    task_filters = (
        PipelineTask.kind == "process_" + kind,
        PipelineTask.strategy_version == version,
        Article.processing_track == "r1",
    )
    linked_call = exists().where(
        BilledRequest.task_id == PipelineTask.id,
        BilledRequest.article_id == PipelineTask.article_id,
        BilledRequest.stage == kind,
    )
    attempted = (
        select(PipelineTask.article_id)
        .join(Article, Article.id == PipelineTask.article_id)
        .where(*task_filters, or_(PipelineTask.attempts > 0, linked_call))
    )
    candidates = (
        session.scalar(select(func.count()).select_from(attempted.distinct().subquery())) or 0
    )
    ready = (
        select(func.count(func.distinct(Article.id if kind == "card" else ContentDerivation.id)))
        .select_from(ContentDerivation)
        .join(
            PipelineTask,
            (PipelineTask.article_id == ContentDerivation.article_id)
            & (PipelineTask.input_fingerprint == ContentDerivation.input_fingerprint),
        )
        .join(Article, Article.id == PipelineTask.article_id)
        .where(
            *task_filters,
            or_(PipelineTask.attempts > 0, linked_call),
            ContentDerivation.kind == ("admission" if kind == "card" else "guide"),
            ContentDerivation.contract_version == version,
            ContentDerivation.status == "ready",
        )
    )
    calls = list(
        session.execute(
            select(BilledRequest.status, BilledRequest.reserved_usd, LlmUsage.cost_usd)
            .join(PipelineTask, PipelineTask.id == BilledRequest.task_id)
            .join(Article, Article.id == PipelineTask.article_id)
            .outerjoin(LlmUsage, LlmUsage.id == BilledRequest.usage_id)
            .where(
                *task_filters,
                BilledRequest.stage == kind,
                BilledRequest.article_id == PipelineTask.article_id,
            )
        )
    )
    known = [amount for row in calls if (amount := _known(row.cost_usd)) is not None]
    unknown = [row for row in calls if _known(row.cost_usd) is None]
    return {
        "contract_version": version,
        "attempted_candidates": candidates,
        "ready_outputs": session.scalar(ready) or 0,
        "physical_requests": len(calls),
        "known_requests": len(known),
        # No requests is a proven zero; an unknown-only cohort has no known cost.
        "known_cost_usd": str(sum(known, Decimal(0))) if known or not calls else None,
        "unknown_requests": len(unknown),
        "held_usd": str(
            sum(
                (
                    row.reserved_usd
                    for row in unknown
                    if row.status in {"reserved", "usage_unknown"}
                ),
                Decimal(0),
            )
        ),
        "unknown_without_hold": sum(
            row.status not in {"reserved", "usage_unknown"} or row.reserved_usd <= 0
            for row in unknown
        ),
    }


def content_unit_costs(session: Session) -> dict[str, Any]:
    # Imported lazily: content parsing itself imports the common LLM client.
    from unspun.core.content_reading import CARD_VERSION, GUIDE_VERSION

    card = _cohort(session, "card", CARD_VERSION)
    guide = _cohort(session, "guide", GUIDE_VERSION)
    total = (
        session.scalar(
            select(func.count())
            .select_from(BilledRequest)
            .where(BilledRequest.stage.in_(["card", "guide"]))
        )
        or 0
    )
    return {
        "basis": "all_time_current_contract_runtime_tasks; not discovery recall or user worth",
        "cohorts": {"card": card, "guide": guide},
        "per_100_candidates": _metric(
            card,
            card["attempted_candidates"],
            "distinct_r1_candidates_with_attempted_card_tasks",
            100,
        ),
        "per_admitted_item": _metric(
            card, card["ready_outputs"], "distinct_current_contract_ready_admissions"
        ),
        "per_new_guide": _metric(
            guide, guide["ready_outputs"], "distinct_current_contract_ready_guide_versions"
        ),
        "excluded_physical_requests": total
        - card["physical_requests"]
        - guide["physical_requests"],
        "exclusion_basis": (
            "Other contracts or missing/mismatched runtime task links; retained in the "
            "overall ledger, never assigned to these cohorts."
        ),
        "monthly_projection": {
            "status": "unmeasured",
            "basis": "requires_registered_observed_eligible_daily_volume",
        },
    }
