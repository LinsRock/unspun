"""Recovery/concurrency on committed rows in the explicitly migrated test DB."""

import os
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import httpx
import pytest
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

from unspun.core.config import get_settings
from unspun.core.content import fingerprint
from unspun.core.task_models import PipelineTask, SourceState, TaskAttempt
from unspun.core.tasks import (
    Lease,
    Queue,
    claim,
    complete,
    enqueue,
    fail,
    reap_expired,
    schedule_sources,
)
from unspun.pipeline.r1_worker import (
    Blocked,
    Deferred,
    Handlers,
    SessionScope,
    WorkerPool,
    process_one,
)


@dataclass
class TaskDB:
    prefix: str
    scope: SessionScope

    def add(self, name: str = "one", queue: Queue = "discovery", **extra: Any) -> int:
        with self.scope() as session:
            return enqueue(
                session,
                queue=queue,
                kind="probe",
                object_key=f"{self.prefix}:{name}",
                input_fingerprint=fingerprint(name),
                strategy_version="synthetic-v1",
                payload=extra.pop("payload", {"name": name}),
                due_at=extra.pop("due_at", datetime.now(UTC) - timedelta(seconds=1)),
                **extra,
            )


@pytest.fixture
def task_db(db_session: Session) -> Generator[TaskDB]:
    # The standard fixture verifies schema availability. Independent connections
    # are essential here: uncommitted fixture rows cannot test SKIP LOCKED.
    assert os.environ.get("UNSPUN_DATABASE_URL"), "an explicit isolated database is required"
    engine = create_engine(get_settings().database_url, pool_size=8, max_overflow=8)

    @contextmanager
    def scope() -> Generator[Session]:
        with Session(engine) as session:
            try:
                yield session
                session.commit()
            except BaseException:
                session.rollback()
                raise

    prefix = f"synthetic-{uuid.uuid4().hex}"
    yield TaskDB(prefix, scope)
    with scope() as session:
        ids = list(
            session.scalars(
                select(PipelineTask.id).where(
                    PipelineTask.object_key.startswith(prefix)
                    | PipelineTask.source_id.startswith(prefix)
                )
            )
        )
        session.execute(delete(TaskAttempt).where(TaskAttempt.task_id.in_(ids)))
        session.execute(delete(PipelineTask).where(PipelineTask.id.in_(ids)))
        session.execute(delete(SourceState).where(SourceState.source_id.startswith(prefix)))
    engine.dispose()


def take(db: TaskDB, queue: Queue = "discovery", **extra: Any) -> Lease | None:
    with db.scope() as session:
        return claim(session, queue=queue, kinds={"probe"}, worker="synthetic-worker", **extra)


def test_duplicate_delivery_and_payload_conflict(task_db: TaskDB) -> None:
    identity = task_db.add()
    assert task_db.add() == identity
    with pytest.raises(ValueError, match="payload"):
        task_db.add(payload={"different": True})
    with task_db.scope() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(PipelineTask)
                .where(PipelineTask.object_key == f"{task_db.prefix}:one")
            )
            == 1
        )


def test_two_real_consumers_have_one_claim_and_one_result(task_db: TaskDB) -> None:
    identity = task_db.add()
    barrier = threading.Barrier(2)

    def contender(index: int) -> Lease | None:
        with task_db.scope() as session:
            barrier.wait(timeout=5)
            return claim(session, queue="discovery", kinds={"probe"}, worker=f"actor-{index}")

    with ThreadPoolExecutor(max_workers=2) as pool:
        leases = [lease for lease in pool.map(contender, range(2)) if lease is not None]
    assert len(leases) == 1
    lease = leases[0]
    with task_db.scope() as session:
        assert complete(session, lease, apply=lambda _: {"winner": lease.worker})
    with task_db.scope() as session:
        assert not complete(session, lease, apply=lambda _: pytest.fail("duplicate business write"))
        assert (
            session.scalar(
                select(func.count()).select_from(TaskAttempt).where(TaskAttempt.task_id == identity)
            )
            == 1
        )
        assert session.get(PipelineTask, identity).status == "completed"  # type: ignore[union-attr]


def test_canonical_object_serializes_different_stages(task_db: TaskDB) -> None:
    task_db.add()
    paid = task_db.add(queue="paid")
    first = take(task_db)
    assert first is not None
    assert take(task_db, "paid") is None
    with task_db.scope() as session:
        complete(session, first, apply=lambda _: {})
    second = take(task_db, "paid")
    assert second is not None and second.task_id == paid


def test_expiry_recovers_and_late_actor_cannot_overwrite(task_db: TaskDB) -> None:
    now = datetime.now(UTC)
    identity = task_db.add(due_at=now - timedelta(seconds=1))
    old = take(task_db, now=now, lease_seconds=1)
    assert old is not None
    expired = now + timedelta(seconds=2)
    with task_db.scope() as session:
        assert not complete(session, old, apply=lambda _: pytest.fail("expired write"), now=expired)
        assert reap_expired(session, expired) == 1
    assert take(task_db, now=expired) is None
    recovered_at = expired + timedelta(seconds=61)
    new = take(task_db, now=recovered_at)
    assert new is not None and new.version == old.version + 1
    with task_db.scope() as session:
        assert not complete(
            session, old, apply=lambda _: pytest.fail("late write"), now=recovered_at
        )
        assert complete(session, new, apply=lambda _: {"version": new.version}, now=recovered_at)
    with task_db.scope() as session:
        assert session.get(PipelineTask, identity).result == {"version": new.version}  # type: ignore[union-attr]
        assert session.get(TaskAttempt, old.attempt_id).status == "lease_expired"  # type: ignore[union-attr]


def test_result_and_successor_are_atomic(task_db: TaskDB) -> None:
    identity = task_db.add()
    lease = take(task_db)
    assert lease is not None

    def apply(session: Session, crash: bool) -> dict[str, Any]:
        successor = enqueue(
            session,
            queue="material",
            kind="probe",
            object_key=f"{task_db.prefix}:next",
            input_fingerprint=fingerprint("next"),
            strategy_version="synthetic-v1",
            payload={},
        )
        if crash:
            raise RuntimeError("synthetic business write failure")
        return {"successor": successor}

    with pytest.raises(RuntimeError), task_db.scope() as session:
        complete(session, lease, apply=lambda db: apply(db, True))
    with task_db.scope() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(PipelineTask)
                .where(PipelineTask.object_key == f"{task_db.prefix}:next")
            )
            == 0
        )
        assert session.get(PipelineTask, identity).status == "running"  # type: ignore[union-attr]
        assert complete(session, lease, apply=lambda db: apply(db, False))
    with task_db.scope() as session:
        assert not complete(session, lease, apply=lambda db: apply(db, False))
        assert (
            session.scalar(
                select(func.count())
                .select_from(PipelineTask)
                .where(PipelineTask.object_key == f"{task_db.prefix}:next")
            )
            == 1
        )


def test_budget_wait_does_not_exhaust_fault_retries(task_db: TaskDB) -> None:
    identity = task_db.add(max_attempts=2)
    now = datetime.now(UTC)
    for _ in range(3):
        lease = take(task_db, now=now)
        assert lease is not None
        with task_db.scope() as session:
            assert fail(
                session,
                lease,
                error="synthetic budget wait",
                now=now,
                retry_at=now + timedelta(hours=1),
                disposition="budget",
            )
        now += timedelta(hours=1, seconds=1)
    for index in range(2):
        lease = take(task_db, now=now)
        assert lease is not None
        with task_db.scope() as session:
            assert fail(session, lease, error="synthetic poison", now=now)
        now += timedelta(hours=1)
        assert (take(task_db, now=now) is None) if index == 1 else True
    with task_db.scope() as session:
        task = session.get(PipelineTask, identity)
        assert task is not None and task.status == "failed"
        assert task.attempts == 5 and task.failures == 2
        assert (
            session.scalar(
                select(func.count()).select_from(TaskAttempt).where(TaskAttempt.task_id == identity)
            )
            == 5
        )


@pytest.mark.parametrize("after_result", [False, True])
def test_real_process_exit_preserves_committed_claim_or_result(
    task_db: TaskDB, after_result: bool
) -> None:
    identity = task_db.add()
    code = f"""
import os
from unspun.core.db import session_scope
from unspun.core.tasks import claim,complete,enqueue
with session_scope() as session:
    lease=claim(session,queue="discovery",kinds={{"probe"}},worker="exit-probe",lease_seconds=1)
assert lease is not None and lease.task_id=={identity}
if {after_result!r}:
    with session_scope() as session:
        def apply(db):
            enqueue(db,queue="material",kind="probe",
                    object_key={task_db.prefix + ":next"!r},
                    input_fingerprint="synthetic",strategy_version="v1",payload={{}})
            return {{"committed":True}}
        assert complete(session,lease,apply=apply)
os._exit(17)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=os.environ,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 17, result.stderr
    after_expiry: datetime | None = None
    with task_db.scope() as session:
        task = session.get(PipelineTask, identity)
        assert task is not None
        if after_result:
            assert task.status == "completed" and task.result == {"committed": True}
            assert claim(session, queue="discovery", kinds={"probe"}, worker="restart") is None
        else:
            assert task.status == "running" and task.lease_until is not None
            after_expiry = task.lease_until + timedelta(seconds=1)
            reap_expired(session, after_expiry)
    if not after_result:
        assert after_expiry is not None
        restored = take(task_db, now=after_expiry + timedelta(seconds=61))
        assert restored is not None and restored.version == 2


def test_schedule_is_single_owner_single_cycle_and_no_catchup_burst(task_db: TaskDB) -> None:
    now = datetime.now(UTC)
    names = {f"{task_db.prefix}-{suffix}" for suffix in ("active", "disabled", "legacy")}
    with task_db.scope() as session:
        for name in names:
            session.add(
                SourceState(
                    source_id=name,
                    owner="legacy" if name.endswith("legacy") else "r1",
                    enabled=not name.endswith("disabled"),
                    period_seconds=1800,
                    schedule_version="synthetic-v1",
                    next_due_at=now - timedelta(days=7),
                )
            )
    with task_db.scope() as session:
        assert schedule_sources(session, names, now) == 1
    with task_db.scope() as session:
        assert schedule_sources(session, names, now) == 0
        assert (
            session.scalar(
                select(func.count())
                .select_from(PipelineTask)
                .where(PipelineTask.source_id.in_(names))
            )
            == 1
        )


def test_periodic_scan_cannot_bypass_source_backoff_or_accumulate(task_db: TaskDB) -> None:
    now = datetime.now(UTC)
    source = task_db.prefix + "-backoff"
    with task_db.scope() as session:
        session.add(
            SourceState(
                source_id=source,
                owner="r1",
                enabled=True,
                period_seconds=60,
                schedule_version="synthetic-v1",
                next_due_at=now,
            )
        )
    with task_db.scope() as session:
        assert schedule_sources(session, {source}, now) == 1
    with task_db.scope() as session:
        lease = claim(
            session, queue="discovery", kinds={"discover"}, worker="source-probe", now=now
        )
        assert lease is not None
        assert fail(
            session, lease, error="synthetic rate limit", now=now, retry_at=now + timedelta(hours=1)
        )
    for minutes in (1, 10, 30, 59):
        with task_db.scope() as session:
            assert schedule_sources(session, {source}, now + timedelta(minutes=minutes)) == 0
            assert (
                claim(
                    session,
                    queue="discovery",
                    kinds={"discover"},
                    worker="must-wait",
                    now=now + timedelta(minutes=minutes),
                )
                is None
            )
    with task_db.scope() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(PipelineTask)
                .where(PipelineTask.source_id == source)
            )
            == 1
        )
        retry_time = now + timedelta(hours=1, seconds=1)
        recovered = claim(
            session, queue="discovery", kinds={"discover"}, worker="recovered", now=retry_time
        )
        assert recovered is not None and recovered.task_id == lease.task_id
        assert complete(session, recovered, apply=lambda _: {}, now=retry_time)
    with task_db.scope() as session:
        state = session.get(SourceState, source)
        assert state is not None and state.consecutive_failures == 0
        assert state.last_success_at == retry_time


@pytest.mark.parametrize("disable", [False, True])
def test_queued_discovery_rechecks_owner_and_enabled_state(task_db: TaskDB, disable: bool) -> None:
    now = datetime.now(UTC)
    source_id = task_db.prefix + "-handoff"
    with task_db.scope() as session:
        session.add(
            SourceState(
                source_id=source_id,
                owner="r1",
                enabled=True,
                period_seconds=60,
                schedule_version="synthetic-v1",
                next_due_at=now,
            )
        )
    with task_db.scope() as session:
        schedule_sources(session, {source_id}, now)
    with task_db.scope() as session:
        source = session.get(SourceState, source_id)
        assert source is not None
        if disable:
            source.enabled = False
        else:
            source.owner = "legacy"
    with task_db.scope() as session:
        assert (
            claim(session, queue="discovery", kinds={"discover"}, worker="stale-schedule", now=now)
            is None
        )


class ProbeHandler:
    def run(self, lease: Lease) -> dict[str, Any]:
        if "url" in lease.payload:
            response = httpx.get(lease.payload["url"], timeout=12)
            response.raise_for_status()
        return {"probe": lease.object_key}

    def apply(self, session: Session, lease: Lease, result: Any) -> dict[str, Any]:
        return {"probe": result["probe"]}


@pytest.mark.parametrize("budget", [False, True])
def test_worker_records_material_blocks_and_budget_waits(task_db: TaskDB, budget: bool) -> None:
    identity = task_db.add()

    class DeferredProbe(ProbeHandler):
        def run(self, lease: Lease) -> dict[str, Any]:
            if budget:
                raise Deferred(
                    "synthetic budget wait", datetime.now(UTC) + timedelta(hours=1), True
                )
            raise Blocked("synthetic restricted material")

    assert process_one(
        "discovery",
        {("discovery", "probe"): DeferredProbe()},
        worker="synthetic",
        scope=task_db.scope,
    )
    with task_db.scope() as session:
        task = session.get(PipelineTask, identity)
        assert task is not None
        assert task.status == ("budget_deferred" if budget else "blocked")
        assert task.attempts == 1 and task.failures == 0


def test_slow_real_http_does_not_block_other_source_material_or_deadline(task_db: TaskDB) -> None:
    entered, release = threading.Event(), threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/slow":
                entered.set()
                release.wait(10)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"probe")

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    slow = task_db.add("slow", payload={"url": url + "/slow"})
    scheduled = threading.Event()
    deadline_ids: list[int] = []

    def schedule() -> None:
        if entered.is_set() and not scheduled.is_set():
            deadline_ids.append(task_db.add("deadline", "deadline"))
            scheduled.set()

    handlers: Handlers = {
        (queue, "probe"): ProbeHandler() for queue in ("discovery", "material", "deadline")
    }
    pool = WorkerPool(
        handlers,
        slots={"discovery": 2, "material": 1, "deadline": 1},
        scope=task_db.scope,
        poll_seconds=0.02,
        scheduler=schedule,
    )
    pool.start()
    try:
        assert entered.wait(5)
        fast = task_db.add("fast", payload={"url": url + "/fast"})
        material = task_db.add("material", "material")
        assert scheduled.wait(5)
        deadline = deadline_ids[0]
        until = time.monotonic() + 5
        while time.monotonic() < until:
            with task_db.scope() as session:
                rows = list(
                    session.scalars(
                        select(PipelineTask).where(PipelineTask.id.in_([fast, material, deadline]))
                    )
                )
                if all(row.status == "completed" for row in rows):
                    break
            time.sleep(0.02)
        else:
            pytest.fail(
                "independent lanes did not finish while the source HTTP request was blocked"
            )
        with task_db.scope() as session:
            assert session.get(PipelineTask, slow).status == "running"  # type: ignore[union-attr]
    finally:
        release.set()
        pool.stop(grace_seconds=3)
        server.shutdown()
        server.server_close()


def test_unregistered_and_disabled_paid_handlers_do_not_consume(task_db: TaskDB) -> None:
    identity = task_db.add(queue="paid")
    assert not process_one("paid", {}, worker="probe", scope=task_db.scope)
    pool = WorkerPool({("paid", "probe"): ProbeHandler()}, scope=task_db.scope)
    pool.start()
    pool.stop()
    assert not pool.threads
    empty = WorkerPool({("discovery", "probe"): ProbeHandler()}, slots={}, scope=task_db.scope)
    empty.start()
    empty.stop()
    assert not empty.threads
    with task_db.scope() as session:
        assert session.get(PipelineTask, identity).status == "pending"  # type: ignore[union-attr]


def test_shared_client_budget_failure_does_not_exhaust_task(task_db: TaskDB) -> None:
    from unspun.core.billing import BudgetExceeded

    task_id = task_db.add(queue="paid")

    class BudgetHandler:
        def run(self, lease: Lease) -> Any:
            raise BudgetExceeded("synthetic shared budget exhaustion")

        def apply(self, session: Session, lease: Lease, result: Any) -> dict[str, Any]:
            pytest.fail("budget failure cannot publish a result")

    assert process_one(
        "paid", {("paid", "probe"): BudgetHandler()}, worker="test", scope=task_db.scope
    )
    with task_db.scope() as session:
        row = session.get(PipelineTask, task_id)
        assert row and row.status == "budget_deferred" and row.failures == 0
