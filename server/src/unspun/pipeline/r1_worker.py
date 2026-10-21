"""Independent bounded R1 execution slots; no legacy pipeline or paid defaults."""

import threading
import time
import uuid
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from unspun.core.billing import BudgetExceeded
from unspun.core.db import session_scope
from unspun.core.logging import get_logger
from unspun.core.tasks import Lease, Queue, claim, complete, fail

log = get_logger("unspun.r1.worker")


class StageHandler(Protocol):
    def run(self, lease: Lease) -> Any:
        """Network/CPU work without an open task transaction."""
        ...

    def apply(self, session: Session, lease: Lease, result: Any) -> dict[str, Any]:
        """Only short DB writes; successors enqueue in this same transaction."""
        ...


@dataclass
class Deferred(Exception):
    reason: str
    until: datetime
    budget: bool = False


@dataclass
class Blocked(Exception):
    reason: str


class DependencyPending(Deferred):
    """A prerequisite wait consumes no execution-failure attempts."""


SessionScope = Callable[[], AbstractContextManager[Session]]
Handlers = Mapping[tuple[Queue, str], StageHandler]


def process_one(
    queue: Queue,
    handlers: Handlers,
    *,
    worker: str,
    scope: SessionScope = session_scope,
    lease_seconds: int = 300,
    source_ids: set[str] | None = None,
    task_ids: frozenset[int] | None = None,
) -> bool:
    kinds = {kind for (lane, kind) in handlers if lane == queue}
    try:
        with scope() as session:
            lease = claim(
                session,
                queue=queue,
                kinds=kinds,
                worker=worker,
                lease_seconds=lease_seconds,
                source_ids=source_ids,
                task_ids=task_ids,
            )
    except IntegrityError as error:
        # Two different pending tasks can race for one canonical object. The
        # partial unique index rejects one; its entire claim transaction rolls back.
        if (
            getattr(getattr(error.orig, "diag", None), "constraint_name", None)
            != "uq_pipeline_tasks_active_object"
        ):
            raise
        return False
    if lease is None:
        return False
    handler = handlers[(queue, lease.kind)]
    try:
        result = handler.run(lease)
        with scope() as session:
            accepted = complete(session, lease, apply=lambda db: handler.apply(db, lease, result))
        if not accepted:
            log.info("stale_result_discarded", task_id=lease.task_id, version=lease.version)
    except BudgetExceeded as error:
        with scope() as session:
            fail(session, lease, error=str(error), retry_at=error.retry_at, disposition="budget")
    except DependencyPending as error:
        with scope() as session:
            fail(session, lease, error=error.reason, retry_at=error.until, disposition="dependency")
    except Deferred as error:
        with scope() as session:
            fail(
                session,
                lease,
                error=error.reason,
                retry_at=error.until,
                disposition="budget" if error.budget else "retry",
            )
    except Blocked as error:
        with scope() as session:
            fail(session, lease, error=error.reason, disposition="blocked")
    except Exception as error:
        with scope() as session:
            # Transport/provider details must not copy request headers into logs.
            fail(session, lease, error=type(error).__name__)
        log.warning("task_failed", task_id=lease.task_id, error_type=type(error).__name__)
    return True


class WorkerPool:
    def __init__(
        self,
        handlers: Handlers,
        *,
        slots: Mapping[Queue, int] | None = None,
        scope: SessionScope = session_scope,
        poll_seconds: float = 1,
        scheduler: Callable[[], None] | None = None,
        stage_sources: Mapping[Queue, set[str]] | None = None,
        lease_seconds: int = 300,
    ) -> None:
        if not 0.01 <= poll_seconds <= 60:
            raise ValueError("poll interval must be between 0.01 and 60 seconds")
        limits: Mapping[Queue, int] = (
            {
                "discovery": 2,
                "material": 2,
                "paid": 0,
                "guide": 0,
                "deadline": 1,
            }
            if slots is None
            else slots
        )
        if any(value < 0 or value > 8 for value in limits.values()):
            raise ValueError("each queue must have between zero and eight slots")
        self.handlers, self.scope, self.poll_seconds = handlers, scope, poll_seconds
        self.scheduler = scheduler
        self.stage_sources = stage_sources
        self.lease_seconds = lease_seconds
        self.slots = dict(limits)
        self.stopping = threading.Event()
        self.threads: list[threading.Thread] = []
        self.worker_id = uuid.uuid4().hex

    def _run(self, queue: Queue, slot: int) -> None:
        while not self.stopping.is_set():
            try:
                worked = process_one(
                    queue,
                    self.handlers,
                    scope=self.scope,
                    worker=f"{self.worker_id}:{queue}:{slot}",
                    source_ids=(
                        self.stage_sources.get(queue, set())
                        if self.stage_sources is not None
                        else None
                    ),
                    lease_seconds=self.lease_seconds,
                )
            except Exception as error:
                log.error("queue_poll_failed", queue=queue, error_type=type(error).__name__)
                worked = False
            if not worked:
                self.stopping.wait(self.poll_seconds)

    def _schedule(self) -> None:
        while not self.stopping.is_set():
            try:
                if self.scheduler is not None:
                    self.scheduler()
            except Exception as error:
                log.error("scheduler_failed", error_type=type(error).__name__)
            self.stopping.wait(self.poll_seconds)

    def start(self) -> None:
        if self.threads:
            raise RuntimeError("worker pool can only be started once")
        for queue, count in self.slots.items():
            if not any(lane == queue for lane, _ in self.handlers):
                continue
            for index in range(count):
                thread = threading.Thread(target=self._run, args=(queue, index), daemon=True)
                self.threads.append(thread)
                thread.start()
        if self.scheduler is not None:
            thread = threading.Thread(target=self._schedule, daemon=True)
            self.threads.append(thread)
            thread.start()

    def stop(self, grace_seconds: float = 5) -> None:
        self.stopping.set()
        deadline = time.monotonic() + grace_seconds
        for thread in self.threads:
            thread.join(timeout=max(0, deadline - time.monotonic()))


def main() -> None:
    from unspun.pipeline.r1_runtime import main as run

    run()


if __name__ == "__main__":
    main()
