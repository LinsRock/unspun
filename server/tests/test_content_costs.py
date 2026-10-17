"""Real PostgreSQL cost denominators, request reuse, and unknown-only cohorts."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

import pytest
from sqlalchemy.orm import Session

from unspun.core.billing import budget_status
from unspun.core.billing_models import BilledRequest
from unspun.core.content_costs import content_unit_costs
from unspun.core.content_reading import CARD_VERSION, GUIDE_VERSION
from unspun.core.models import Article, ContentDerivation, ContentMaterial, LlmUsage
from unspun.core.task_models import PipelineTask
from unspun.core.tasks import enqueue


def article(session: Session) -> Article:
    row = Article(
        source_id="synthetic-cost",
        title="Synthetic cost cohort",
        url="https://example.org/" + uuid.uuid4().hex,
        lang="en",
        processing_track="r1",
    )
    session.add(row)
    session.flush()
    return row


def task(
    session: Session,
    item: Article,
    kind: Literal["card", "guide"] = "card",
    *,
    version: str | None = None,
    fp: str = "first",
    attempts: int = 1,
) -> PipelineTask:
    identity = enqueue(
        session,
        queue="paid" if kind == "card" else "guide",
        kind="process_" + kind,
        article_id=item.id,
        source_id=item.source_id,
        object_key="cost:" + str(item.id),
        input_fingerprint=fp,
        strategy_version=version or (CARD_VERSION if kind == "card" else GUIDE_VERSION),
        payload={},
    )
    row = session.get(PipelineTask, identity)
    assert row is not None
    row.attempts = attempts
    session.flush()
    return row


def ready(session: Session, item: Article, work: PipelineTask, kind: str) -> None:
    material = ContentMaterial(
        article_id=item.id,
        input_fingerprint=work.input_fingerprint,
        text_fingerprint=uuid.uuid4().hex,
        metadata_fingerprint="synthetic",
        extractor_version="synthetic",
        schema_version="synthetic",
        scope="open_text_unit",
        access_status="ok",
        completeness="observed_unit",
        completeness_basis="Synthetic cost fixture",
        source_url=item.url,
        retrieved_at=datetime.now(UTC),
        paragraphs=[],
        evidence={},
    )
    session.add(material)
    session.flush()
    session.add(
        ContentDerivation(
            article_id=item.id,
            material_id=material.id,
            kind=kind,
            status="ready",
            input_fingerprint=work.input_fingerprint,
            metadata_fingerprint="synthetic",
            contract_version=work.strategy_version,
            review_contract="synthetic",
            payload={},
            review_evidence={},
        )
    )
    session.flush()


def call(
    session: Session,
    work: PipelineTask | None,
    *,
    kind: str = "card",
    cost: float | None = None,
    held: str = "0.2",
    article_id: int | None = None,
) -> None:
    usage = (
        LlmUsage(purpose="summary", model="synthetic", cost_usd=cost) if cost is not None else None
    )
    if usage:
        session.add(usage)
        session.flush()
    session.add(
        BilledRequest(
            id=uuid.uuid4().hex,
            purpose="summary",
            stage=kind,
            phase="generate",
            model="synthetic",
            request_fingerprint=uuid.uuid4().hex,
            price_version="synthetic",
            reserved_usd=Decimal(held),
            status="responded" if usage else "usage_unknown",
            task_id=work.id if work else None,
            article_id=article_id or (work.article_id if work else None),
            usage_id=usage.id if usage else None,
        )
    )
    session.flush()


def test_unattempted_and_imported_outputs_are_not_measured(db_session: Session) -> None:
    item = article(db_session)
    work = task(db_session, item, attempts=0)
    ready(db_session, item, work, "admission")
    result = content_unit_costs(db_session)
    assert result["per_100_candidates"]["status"] == "unmeasured"
    assert result["per_admitted_item"]["value_usd"] is None
    assert result["cohorts"]["card"]["ready_outputs"] == 0


def test_card_costs_include_failed_calls_and_count_contents_once(db_session: Session) -> None:
    first = article(db_session)
    original = task(db_session, first)
    ready(db_session, first, original, "admission")
    call(db_session, original, cost=0.01)
    call(db_session, original, cost=0.02)
    changed = task(db_session, first, fp="changed-material")
    ready(db_session, first, changed, "admission")
    call(db_session, changed, cost=0.03)
    failed = task(db_session, article(db_session))
    call(db_session, failed, cost=0.04)
    call(db_session, failed)
    task(db_session, article(db_session))  # A deterministic rejection made no requests.
    result = content_unit_costs(db_session)
    cohort = result["cohorts"]["card"]
    assert cohort["attempted_candidates"] == 3
    assert cohort["ready_outputs"] == 1
    assert cohort["physical_requests"] == 5
    assert Decimal(cohort["known_cost_usd"]) == Decimal("0.10")
    assert cohort["unknown_requests"] == 1
    metric = result["per_admitted_item"]
    assert metric["status"] == "known_lower_bound"
    assert Decimal(metric["value_usd"]) == Decimal("0.10")
    assert Decimal(metric["known_plus_holds_scenario_usd"]) == Decimal("0.30")
    assert result["per_100_candidates"]["denominator_count"] == 3


def test_unknown_only_is_not_zero_and_keeps_full_hold(db_session: Session) -> None:
    work = task(db_session, article(db_session))
    call(db_session, work, held="0.17")
    result = budget_status(db_session)
    metric = result["unit_costs"]["per_100_candidates"]
    assert metric["status"] == "unknown" and metric["value_usd"] is None
    assert Decimal(metric["known_plus_holds_scenario_usd"]) == 17
    assert result["unit_costs"]["cohorts"]["card"]["known_cost_usd"] is None
    assert Decimal(result["reserved_usd"]) == Decimal("0.17")


def test_proven_no_request_rejection_has_zero_cost(db_session: Session) -> None:
    task(db_session, article(db_session))
    metric = content_unit_costs(db_session)["per_100_candidates"]
    assert metric["status"] == "measured" and Decimal(metric["value_usd"]) == 0


@pytest.mark.parametrize("invalid", [-0.5, float("nan")])
def test_invalid_known_fee_has_no_invented_zero_or_upper_bound(
    db_session: Session, invalid: float
) -> None:
    work = task(db_session, article(db_session))
    call(db_session, work, cost=invalid)
    result = content_unit_costs(db_session)
    metric = result["per_100_candidates"]
    assert metric["status"] == "unknown" and metric["value_usd"] is None
    assert metric["known_plus_holds_scenario_usd"] is None
    assert result["cohorts"]["card"]["unknown_without_hold"] == 1


def test_unknown_with_no_positive_hold_has_no_zero_upper_bound(db_session: Session) -> None:
    work = task(db_session, article(db_session))
    call(db_session, work, held="0")
    metric = content_unit_costs(db_session)["per_100_candidates"]
    assert metric["status"] == "unknown"
    assert metric["known_plus_holds_scenario_usd"] is None


def test_new_guides_use_ready_versions_and_exclude_other_associations(db_session: Session) -> None:
    item = article(db_session)
    for fp in ("first", "new-material"):
        work = task(db_session, item, "guide", fp=fp)
        ready(db_session, item, work, "guide")
        call(db_session, work, kind="guide", cost=0.001)
        call(db_session, work, kind="guide", cost=0.005)
        assert task(db_session, item, "guide", fp=fp).id == work.id
    old = task(db_session, item, "guide", version="old-contract", fp="old")
    ready(db_session, item, old, "guide")
    call(db_session, old, kind="guide", cost=0.9)
    call(db_session, None, kind="guide", cost=0.7)
    other = article(db_session)
    call(db_session, work, kind="guide", article_id=other.id)
    result = content_unit_costs(db_session)
    assert result["excluded_physical_requests"] == 3
    assert result["per_new_guide"]["denominator_count"] == 2
    assert Decimal(result["per_new_guide"]["value_usd"]) == Decimal("0.006")
    assert result["cohorts"]["guide"]["physical_requests"] == 4
    assert not db_session.new and not db_session.dirty and not db_session.deleted
