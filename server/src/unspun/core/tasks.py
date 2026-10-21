"""Short-transaction task repository with fencing and atomic successor writes.

Callers commit a claim before network work, then pass its version back to a
completion transaction. No external exactly-once guarantee is made.
"""

import copy
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import exists, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, aliased

from unspun.core.content import fingerprint
from unspun.core.task_models import PipelineTask, SourceState, TaskAttempt

Queue = Literal["discovery", "material", "paid", "guide", "deadline"]


@dataclass(frozen=True)
class Lease:
    task_id: int
    attempt_id: int
    version: int
    kind: str
    queue: str
    object_key: str
    payload: dict[str, Any]
    input_fingerprint: str
    strategy_version: str
    article_id: int | None
    source_id: str | None
    worker: str
    until: datetime


def enqueue(
    session: Session,
    *,
    queue: Queue,
    kind: str,
    object_key: str,
    input_fingerprint: str,
    strategy_version: str,
    payload: dict[str, Any],
    due_at: datetime | None = None,
    cycle_key: str | None = None,
    article_id: int | None = None,
    source_id: str | None = None,
    max_attempts: int = 3,
    priority: int = 0,
) -> int:
    if not kind or not object_key or not strategy_version or not input_fingerprint:
        raise ValueError("task identity must be complete")
    key = fingerprint([queue, kind, object_key, input_fingerprint, strategy_version, cycle_key])
    values = dict(
        queue=queue,
        kind=kind,
        object_key=object_key,
        input_fingerprint=input_fingerprint,
        strategy_version=strategy_version,
        payload=payload,
        due_at=due_at or datetime.now(UTC),
        cycle_key=cycle_key,
        article_id=article_id,
        source_id=source_id,
        max_attempts=max_attempts,
        priority=priority,
        dedupe_key=key,
    )
    identity = session.scalar(
        insert(PipelineTask)
        .values(**values)
        .on_conflict_do_nothing(
            index_elements=[PipelineTask.dedupe_key],
        )
        .returning(PipelineTask.id)
    )
    if identity is not None:
        return identity
    current = session.execute(
        select(
            PipelineTask.id, PipelineTask.payload, PipelineTask.article_id, PipelineTask.source_id
        ).where(PipelineTask.dedupe_key == key)
    ).one()
    if (
        current.payload != payload
        or current.article_id != article_id
        or current.source_id != source_id
    ):
        raise ValueError("task dedupe identity conflicts with immutable payload")
    return current.id


def retry_delay(attempts: int) -> timedelta:
    return timedelta(seconds=min(60 * 2 ** max(0, attempts - 1), 7200))


def _source_failure(session: Session, task: PipelineTask, now: datetime) -> None:
    if task.queue != "discovery" or task.source_id is None:
        return
    with session.no_autoflush:
        source = session.get(SourceState, task.source_id, with_for_update=True)
    if source is None:
        return
    source.consecutive_failures += 1
    seconds = min(
        source.period_seconds * 2 ** min(source.consecutive_failures, 8),
        max(source.period_seconds, 21600),
    )
    source.next_due_at = max(source.next_due_at, now + timedelta(seconds=seconds), task.due_at)
    task.due_at = source.next_due_at


def reap_expired(
    session: Session, now: datetime, limit: int = 100, *, task_ids: frozenset[int] | None = None
) -> int:
    rows = session.scalars(
        select(PipelineTask)
        .where(
            PipelineTask.status == "running",
            PipelineTask.lease_until <= now,
            *([PipelineTask.id.in_(task_ids)] if task_ids is not None else []),
        )
        .order_by(PipelineTask.lease_until, PipelineTask.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    for task in rows:
        attempt = session.scalar(
            select(TaskAttempt).where(
                TaskAttempt.task_id == task.id,
                TaskAttempt.claim_version == task.claim_version,
            )
        )
        if attempt is not None:
            attempt.status, attempt.ended_at, attempt.error = "lease_expired", now, "lease expired"
        task.failures += 1
        task.status = "failed" if task.failures >= task.max_attempts else "retry_wait"
        task.due_at = now + retry_delay(task.failures)
        _source_failure(session, task, now)
        task.finished_at = now if task.status == "failed" else None
        task.lease_until, task.claimed_by, task.last_error = None, None, "lease expired"
    session.flush()
    return len(rows)


def claim(
    session: Session,
    *,
    queue: Queue,
    kinds: set[str],
    worker: str,
    now: datetime | None = None,
    lease_seconds: int = 120,
    source_ids: set[str] | None = None,
    task_ids: frozenset[int] | None = None,
) -> Lease | None:
    if not kinds or source_ids == set() or task_ids == frozenset():
        return None
    if not 1 <= lease_seconds <= 3600:
        raise ValueError("lease must be between 1 and 3600 seconds")
    now = now or datetime.now(UTC)
    reap_expired(session, now, task_ids=task_ids)
    active = aliased(PipelineTask)
    disabled_source = exists(
        select(SourceState.source_id).where(
            SourceState.source_id == PipelineTask.source_id,
            or_(SourceState.owner != "r1", SourceState.enabled.is_(False)),
        )
    )
    task = session.scalar(
        select(PipelineTask)
        .where(
            PipelineTask.queue == queue,
            PipelineTask.kind.in_(kinds),
            *([PipelineTask.id.in_(task_ids)] if task_ids is not None else []),
            *([PipelineTask.source_id.in_(source_ids)] if source_ids is not None else []),
            PipelineTask.status.in_(["pending", "retry_wait", "budget_deferred"]),
            PipelineTask.due_at <= now,
            PipelineTask.failures < PipelineTask.max_attempts,
            or_(PipelineTask.queue != "discovery", ~disabled_source),
            ~exists(
                select(active.id).where(
                    active.object_key == PipelineTask.object_key, active.status == "running"
                )
            ),
        )
        .order_by(PipelineTask.priority.desc(), PipelineTask.due_at, PipelineTask.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if task is None:
        return None
    task.status, task.claimed_by = "running", worker
    task.attempts += 1
    task.claim_version += 1
    until = now + timedelta(seconds=lease_seconds)
    task.lease_until = until
    attempt = TaskAttempt(
        task_id=task.id,
        claim_version=task.claim_version,
        worker=worker,
        started_at=now,
        lease_until=until,
        status="running",
    )
    session.add(attempt)
    # The partial unique index also fences competing tasks for the same object.
    # A caller encountering its race rolls back and tries on the next poll.
    session.flush()
    return Lease(
        task.id,
        attempt.id,
        task.claim_version,
        task.kind,
        task.queue,
        task.object_key,
        copy.deepcopy(task.payload),
        task.input_fingerprint,
        task.strategy_version,
        task.article_id,
        task.source_id,
        worker,
        until,
    )


def _owned(
    session: Session, lease: Lease, now: datetime
) -> tuple[PipelineTask, TaskAttempt] | None:
    task = session.scalar(
        select(PipelineTask)
        .where(
            PipelineTask.id == lease.task_id,
            PipelineTask.status == "running",
            PipelineTask.claim_version == lease.version,
            PipelineTask.claimed_by == lease.worker,
            PipelineTask.lease_until > now,
        )
        .with_for_update()
    )
    if task is None:
        return None
    attempt = session.get(TaskAttempt, lease.attempt_id)
    if attempt is None or attempt.claim_version != lease.version or attempt.task_id != task.id:
        raise ValueError("attempt does not match task lease")
    return task, attempt


def complete(
    session: Session,
    lease: Lease,
    *,
    apply: Callable[[Session], dict[str, Any]],
    now: datetime | None = None,
) -> bool:
    now = now or datetime.now(UTC)
    current = _owned(session, lease, now)
    if current is None:
        return False
    task, attempt = current
    # Business writes and enqueued successors share this transaction/ack.
    task.result = apply(session)
    task.status, task.finished_at, task.lease_until, task.claimed_by = "completed", now, None, None
    attempt.status, attempt.ended_at = "completed", now
    if task.queue == "discovery" and task.source_id is not None:
        source = session.get(SourceState, task.source_id, with_for_update=True)
        if source is not None:
            source.consecutive_failures = 0
            source.last_success_at = now
            bucket = int(now.timestamp()) // source.period_seconds
            source.next_due_at = datetime.fromtimestamp((bucket + 1) * source.period_seconds, UTC)
    return True


def fail(
    session: Session,
    lease: Lease,
    *,
    error: str,
    now: datetime | None = None,
    retry_at: datetime | None = None,
    disposition: Literal["retry", "budget", "dependency", "blocked"] = "retry",
) -> bool:
    now = now or datetime.now(UTC)
    if disposition in {"budget", "dependency"} and (retry_at is None or retry_at <= now):
        raise ValueError("deferral requires a future availability time")
    current = _owned(session, lease, now)
    if current is None:
        return False
    task, attempt = current
    if disposition == "blocked":
        task.status, attempt.status = "blocked", "blocked"
    elif disposition == "budget":
        task.status, attempt.status = "budget_deferred", "deferred"
        # A budget wait is not a failed execution and does not exhaust recovery.
    elif disposition == "dependency":
        task.status, attempt.status = "retry_wait", "deferred"
    else:
        task.failures += 1
        task.status = "failed" if task.failures >= task.max_attempts else "retry_wait"
        attempt.status = "failed"
    task.due_at = retry_at or now + retry_delay(max(1, task.failures))
    if disposition == "retry":
        _source_failure(session, task, now)
    task.finished_at = now if task.status in ("failed", "blocked") else None
    task.lease_until, task.claimed_by = None, None
    task.last_error = error[:2000]
    attempt.error, attempt.ended_at = error[:2000], now
    return True


def schedule_sources(session: Session, source_ids: set[str], now: datetime | None = None) -> int:
    """Schedule at most the current cycle, with no catch-up burst after downtime."""
    now = now or datetime.now(UTC)
    sources = session.scalars(
        select(SourceState)
        .where(
            SourceState.source_id.in_(source_ids),
            SourceState.owner == "r1",
            SourceState.enabled.is_(True),
            SourceState.next_due_at <= now,
            ~exists(
                select(PipelineTask.id).where(
                    PipelineTask.source_id == SourceState.source_id,
                    PipelineTask.queue == "discovery",
                    PipelineTask.status.in_(
                        ["pending", "running", "retry_wait", "budget_deferred"]
                    ),
                )
            ),
        )
        .limit(100)
        .with_for_update(skip_locked=True)
    ).all()
    for source in sources:
        bucket = int(now.timestamp()) // source.period_seconds
        enqueue(
            session,
            queue="discovery",
            kind="discover",
            object_key=f"source:{source.source_id}",
            source_id=source.source_id,
            input_fingerprint=fingerprint(source.schedule_version),
            strategy_version=source.schedule_version,
            cycle_key=str(bucket),
            payload={"source_id": source.source_id, "schedule_version": source.schedule_version},
            due_at=now,
        )
        source.next_due_at = datetime.fromtimestamp((bucket + 1) * source.period_seconds, UTC)
    return len(sources)
