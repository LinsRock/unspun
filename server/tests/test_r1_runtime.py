"""Runtime gates, ownership cutover, and paused backlog on a migrated database."""

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from unspun.core.billing import POLICY_VERSION
from unspun.core.billing_models import BudgetPolicy
from unspun.core.config import Settings
from unspun.core.sources import Source
from unspun.core.task_models import PipelineTask, SourceState
from unspun.core.tasks import Queue, claim, enqueue
from unspun.pipeline.r1_runtime import build_runtime, check_paid_budget, make_pool, sync_sources


def source(identity: str = "runtime-test", **stages: bool) -> Source:
    return Source.model_validate(
        {
            "id": identity,
            "name": "Synthetic source",
            "url": "https://example.com/feed",
            "weight": 0.5,
            "region": "intl",
            "kind": "public",
            "lang": "en",
            "legacy_enabled": False,
            "discovery_owner": "r1",
            "r1": stages,
        }
    )


def test_closed_runtime_has_no_handlers_or_network() -> None:
    runtime = build_runtime([source()], Settings())
    assert not runtime.handlers
    assert not any(runtime.stage_sources.values())
    pool = make_pool(runtime)
    assert not pool.handlers
    assert pool.stage_sources == runtime.stage_sources


def test_source_flags_cannot_override_global_stop() -> None:
    with pytest.raises(ValueError, match="disabled"):
        build_runtime([source(discovery=True)], Settings(r1_worker_enabled=False))


def test_each_registered_stage_uses_its_own_source_allowlist() -> None:
    runtime = build_runtime(
        [source("discovery-only", discovery=True), source("material-only", material=True)],
        Settings(r1_worker_enabled=True),
    )
    assert runtime.stage_sources["discovery"] == {"discovery-only"}
    assert runtime.stage_sources["material"] == {"material-only"}
    assert runtime.stage_sources["paid"] == runtime.stage_sources["guide"] == set()
    assert set(runtime.handlers) == {("discovery", "discover"), ("material", "fetch_material")}
    paid = build_runtime([source(paid=True)], Settings(r1_worker_enabled=True))
    assert set(paid.handlers) == {("paid", "process_card"), ("guide", "process_guide")}


def test_restarting_runtime_preserves_backoff_and_history(db_session: Session) -> None:
    now = datetime.now(UTC)
    due = now + timedelta(hours=3)
    db_session.add_all(
        [
            SourceState(
                source_id=identity,
                owner="r1",
                enabled=True,
                period_seconds=1800,
                schedule_version="previous",
                next_due_at=due,
                consecutive_failures=2,
                last_success_at=now - timedelta(hours=1),
            )
            for identity in ("runtime-test", "removed-route")
        ]
    )
    db_session.flush()
    runtime = build_runtime([source(discovery=True)], Settings(r1_worker_enabled=True))
    sync_sources(db_session, runtime, now=now)
    sync_sources(db_session, runtime, now=now + timedelta(minutes=1))
    db_session.expire_all()
    state = db_session.get(SourceState, "runtime-test")
    assert state is not None and state.enabled
    assert state.next_due_at == due and state.consecutive_failures == 2
    assert state.last_success_at == now - timedelta(hours=1)
    removed = db_session.get(SourceState, "removed-route")
    assert removed is not None and not removed.enabled and removed.next_due_at == due
    sync_sources(db_session, build_runtime([], Settings()), now=now)
    db_session.expire_all()
    assert not state.enabled


@pytest.mark.parametrize("queue", ["discovery", "material", "paid", "guide"])
def test_paused_source_tasks_are_never_claimed(db_session: Session, queue: Queue) -> None:
    for identity in ("paused", "enabled"):
        enqueue(
            db_session,
            queue=queue,
            kind="synthetic-runtime",
            source_id=identity,
            object_key="runtime:" + queue + ":" + identity,
            input_fingerprint="synthetic",
            strategy_version="synthetic",
            payload={},
            priority=100 if identity == "paused" else 0,
        )
    lease = claim(
        db_session,
        queue=queue,
        kinds={"synthetic-runtime"},
        worker="runtime-test",
        source_ids={"enabled"},
    )
    assert lease is not None and lease.source_id == "enabled"
    paused = db_session.scalar(select(PipelineTask).where(PipelineTask.source_id == "paused"))
    assert paused is not None and paused.status == "pending" and paused.attempts == 0
    assert (
        claim(
            db_session,
            queue=queue,
            kinds={"synthetic-runtime"},
            worker="runtime-test",
            source_ids=set(),
        )
        is None
    )


def test_paid_cutover_rejects_missing_evaluation_incident_and_different_key(
    db_session: Session,
) -> None:
    settings = Settings(openrouter_api_key="synthetic-key")
    with pytest.raises(ValueError, match="budget cutover"):
        check_paid_budget(db_session, settings)
    policy = BudgetPolicy(
        id=1,
        scope="evaluation",
        enabled=True,
        monthly_limit_usd=Decimal("0.6"),
        stage_caps={},
        version=POLICY_VERSION,
        key_fingerprint=hashlib.sha256(settings.openrouter_api_key.encode()).hexdigest(),
        provider_observed_at=datetime.now(UTC),
    )
    db_session.add(policy)
    db_session.flush()
    with pytest.raises(ValueError, match="budget cutover"):
        check_paid_budget(db_session, settings)
    policy.scope = "production"
    policy.incident = "synthetic unresolved incident"
    with pytest.raises(ValueError, match="budget cutover"):
        check_paid_budget(db_session, settings)
    policy.incident = None
    policy.key_fingerprint = "different-key"
    with pytest.raises(ValueError, match="budget cutover"):
        check_paid_budget(db_session, settings)
    policy.key_fingerprint = hashlib.sha256(settings.openrouter_api_key.encode()).hexdigest()
    check_paid_budget(db_session, settings)
