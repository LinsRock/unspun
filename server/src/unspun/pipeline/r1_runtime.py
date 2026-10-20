"""Explicit R1 runtime wiring. Source rollout and billing cutover remain separate PR gates."""

import argparse
import hashlib
import json
import signal
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from types import FrameType
from typing import Any

from sqlalchemy import text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from unspun.core.billing import POLICY_VERSION
from unspun.core.billing_models import BudgetPolicy
from unspun.core.config import Settings, get_settings
from unspun.core.content import fingerprint
from unspun.core.db import session_scope
from unspun.core.logging import configure_logging, get_logger
from unspun.core.sources import Source, load_sources
from unspun.core.task_models import SourceState
from unspun.core.tasks import Queue, schedule_sources
from unspun.pipeline.content_processing import ContentHandler
from unspun.pipeline.discovery import DiscoveryHandler
from unspun.pipeline.materials import MaterialHandler
from unspun.pipeline.member_processing import MemberHandler
from unspun.pipeline.r1_worker import Handlers, SessionScope, StageHandler, WorkerPool

log = get_logger("unspun.r1.runtime")


@dataclass(frozen=True)
class Runtime:
    sources: dict[str, Source]
    stage_sources: dict[Queue, set[str]]
    handlers: Handlers
    config_fingerprint: str

    def describe(self) -> dict[str, Any]:
        return {
            "version": "r1-runtime-v1",
            "config_fingerprint": self.config_fingerprint,
            "stages": {stage: sorted(ids) for stage, ids in self.stage_sources.items()},
            "publication": sorted(s.id for s in self.sources.values() if s.r1 and s.r1.publish),
            "legacy_worker_started": False,
            "member_processing_enabled": ("paid", "topic_recall") in self.handlers,
        }


def build_runtime(
    sources: list[Source], settings: Settings, *, scope: SessionScope = session_scope
) -> Runtime:
    selected = {s.id: s for s in sources if s.discovery_owner == "r1" and s.r1}
    stages: dict[Queue, set[str]] = {
        "discovery": {s.id for s in selected.values() if s.r1 and s.r1.discovery},
        "material": {s.id for s in selected.values() if s.r1 and s.r1.material},
        "paid": {s.id for s in selected.values() if s.r1 and s.r1.paid},
        "guide": {s.id for s in selected.values() if s.r1 and s.r1.paid},
    }
    active = any(stages.values())
    if active and not settings.r1_worker_enabled:
        raise ValueError("R1 runtime is disabled; source stages must remain off")
    handlers: dict[tuple[Queue, str], StageHandler] = {}
    if stages["discovery"]:
        handlers[("discovery", "discover")] = DiscoveryHandler(selected)
    if stages["material"]:
        handlers[("material", "fetch_material")] = MaterialHandler(selected)
    if stages["paid"]:
        handlers[("paid", "process_card")] = ContentHandler(selected, scope=scope)
        handlers[("guide", "process_guide")] = ContentHandler(selected, "guide", scope=scope)
        if settings.r2_member_processing_enabled:
            member_handler = MemberHandler(selected, scope=scope)
            for kind in ("topic_recall", "topic_judge", "topic_review"):
                handlers[("paid", kind)] = member_handler
    return Runtime(
        selected,
        stages,
        handlers,
        fingerprint([s.model_dump(mode="json") for s in sorted(sources, key=lambda s: s.id)]),
    )


def check_paid_budget(session: Session, settings: Settings) -> None:
    policy = session.get(BudgetPolicy, 1)
    if (
        not settings.openrouter_api_key
        or policy is None
        or not policy.enabled
        or policy.scope != "production"
        or policy.version != POLICY_VERSION
        or policy.incident
        or policy.key_fingerprint
        != hashlib.sha256(settings.openrouter_api_key.encode()).hexdigest()
        or policy.provider_observed_at is None
    ):
        raise ValueError("R1 paid runtime requires an explicit, valid production budget cutover")


def sync_sources(session: Session, runtime: Runtime, *, now: datetime | None = None) -> None:
    """Persist reviewed ownership while retaining due times, failures, tasks and history."""
    now = now or datetime.now(UTC)
    session.execute(text("SELECT pg_advisory_xact_lock(761719016)"))
    enabled = runtime.stage_sources["discovery"]
    session.execute(
        update(SourceState)
        .where(SourceState.owner == "r1", SourceState.source_id.not_in(enabled))
        .values(enabled=False)
    )
    for source in runtime.sources.values():
        assert source.r1 is not None
        session.execute(
            insert(SourceState)
            .values(
                source_id=source.id,
                owner="r1",
                enabled=source.id in enabled,
                period_seconds=source.r1.period_seconds,
                schedule_version=source.r1.version,
                next_due_at=now,
            )
            .on_conflict_do_update(
                index_elements=[SourceState.source_id],
                set_={
                    "owner": "r1",
                    "enabled": source.id in enabled,
                    "period_seconds": source.r1.period_seconds,
                    "schedule_version": source.r1.version,
                },
            )
        )


def make_pool(runtime: Runtime, *, scope: SessionScope = session_scope) -> WorkerPool:
    def schedule() -> None:
        with scope() as session:
            schedule_sources(session, runtime.stage_sources["discovery"])

    return WorkerPool(
        runtime.handlers,
        slots={"discovery": 2, "material": 2, "paid": 1, "guide": 1},
        stage_sources=runtime.stage_sources,
        lease_seconds=900,
        scope=scope,
        poll_seconds=5,
        scheduler=schedule,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="read-only configuration preflight")
    parser.add_argument("--run-seconds", type=int, help="bounded execution for isolated validation")
    args = parser.parse_args()
    if args.run_seconds is not None and not 1 <= args.run_seconds <= 86400:
        parser.error("run-seconds must be between 1 and 86400")
    configure_logging()
    settings = get_settings()
    try:
        runtime = build_runtime(load_sources(), settings)
        if runtime.stage_sources["paid"]:
            with session_scope() as session:
                check_paid_budget(session, settings)
        print(json.dumps(runtime.describe(), sort_keys=True), flush=True)
        if args.check:
            return
        if not settings.r1_worker_enabled or not runtime.handlers:
            raise ValueError("R1 runtime has no authorized active stages")
        with session_scope() as session:
            sync_sources(session, runtime)
    except ValueError as error:
        log.error("runtime_preflight_failed", reason=str(error))
        raise SystemExit(2) from None
    stopped = threading.Event()

    def stop(_signum: int, _frame: FrameType | None) -> None:
        stopped.set()

    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, stop)
    pool = make_pool(runtime)
    pool.start()
    log.info("runtime_started", **runtime.describe())
    try:
        stopped.wait(args.run_seconds)
    finally:
        pool.stop(grace_seconds=30)
        log.info("runtime_stopped")


if __name__ == "__main__":
    main()
