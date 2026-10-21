"""Frozen R2-06 retest; one original ledger, sealed holdout and retained first outputs."""

import argparse
import hashlib
import json
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import httpx
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from unspun.core.billing import BudgetExceeded, CallContext, budget_status
from unspun.core.billing_admin import provider_key_status
from unspun.core.billing_models import BilledRequest
from unspun.core.config import get_settings
from unspun.core.content import fingerprint
from unspun.core.db import get_engine
from unspun.core.llm import LlmClient
from unspun.core.member_contracts import member_contract
from unspun.core.member_models import ContentVector
from unspun.core.member_recall import current_input, vector_input
from unspun.core.sources import load_sources
from unspun.core.task_models import PipelineTask, TaskAttempt
from unspun.evaluation.member_quality import (
    ROOT,
    RUN_LOCK,
    MemberBatchJournal,
    batch_state,
    registration,
    require_original_database,
    seed_packages,
    seed_topics,
)
from unspun.evaluation.run_quality import load_key_from_ssh
from unspun.pipeline.member_processing import MemberHandler, enqueue_member_processing
from unspun.pipeline.r1_worker import Handlers, process_one

EVIDENCE = ROOT / "docs/acceptance/r2-06-repair"
EXECUTION = ROOT / "docs/evaluations/r2/member-retest-v1.json"
UNFINISHED = ("pending", "running", "retry_wait", "budget_deferred")


def phase_tasks(session: Session, identity: str) -> list[PipelineTask]:
    return list(
        session.scalars(
            select(PipelineTask)
            .where(
                PipelineTask.id.in_(
                    select(TaskAttempt.task_id).where(TaskAttempt.worker == identity)
                )
            )
            .order_by(PipelineTask.id)
        )
    )


def phase_request_count(session: Session, identity: str) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(BilledRequest)
            .join(TaskAttempt, BilledRequest.task_attempt_id == TaskAttempt.id)
            .where(TaskAttempt.worker == identity)
        )
        or 0
    )


def limits_reached(
    session: Session, spec: dict[str, Any], execution: dict[str, Any], phase: str, cap: Decimal
) -> bool:
    state, budget = batch_state(session), spec["budget"]
    return (
        phase_request_count(session, spec["id"])
        >= execution["phases"][phase]["physical_request_limit"]
        or state["physical_requests"] >= budget["physical_request_limit"]
        or any(
            state["stage_counts"][stage] >= limit
            for stage, limit in budget["stage_physical_limits"].items()
        )
        or Decimal(state["known_usd"]) + Decimal(state["held_usd"]) >= cap
    )


def load_execution() -> dict[str, Any]:
    value = json.loads(EXECUTION.read_text())
    freeze = json.loads((ROOT / "docs/evaluations/r2/member-repair-freeze-v1.json").read_text())
    for row in freeze["files"]:
        if hashlib.sha256((ROOT / row["path"]).read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError("frozen retest source or registration changed")
    if value["contract"] != member_contract():
        raise ValueError("frozen retest contract changed")
    return value


def require_phase_complete(
    engine: Engine, execution: dict[str, Any], phase: str, spec: dict[str, Any]
) -> None:
    path = EVIDENCE / f"{phase}-first-run.ndjson"
    if not path.exists():
        raise ValueError("regression must complete before opening the sealed holdout")
    final = json.loads(path.read_text().splitlines()[-1])
    excluded = {item["article_id"] for item in spec.get("unavailable_inputs", [])}
    expected = [q["article_id"] for q in spec["queries"] if q["article_id"] not in excluded]
    if (
        final.get("event") != "complete"
        or final.get("registration") != spec["id"]
        or final.get("execution_fingerprint") != fingerprint(execution)
        or final.get("contract") != member_contract()
        or final.get("completed_queries") != expected
    ):
        raise ValueError("regression must complete with the exact frozen execution and query set")
    with Session(engine) as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        tasks = phase_tasks(session, spec["id"])
        if (
            sorted(t.id for t in tasks) != final["task_ids"]
            or any(t.status not in {"completed", "failed", "blocked"} for t in tasks)
            or {t.article_id for t in tasks if t.kind == "topic_recall"} != set(expected)
            or session.scalar(
                select(PipelineTask.id)
                .where(PipelineTask.queue == "paid", PipelineTask.status.in_(UNFINISHED))
                .limit(1)
            )
            is not None
        ):
            raise ValueError("registered phase still has unfinished or mismatched tasks")


def phase_spec(
    execution: dict[str, Any], phase: str, *, engine: Engine | None = None
) -> dict[str, Any]:
    if phase == "regression":
        spec = registration(require_current_contract=False)
        spec["id"] = execution["id"] + ":regression"
        for topic in spec["topics"]:
            topic["original_id"] = topic["id"]
            topic["id"] = str(uuid5(NAMESPACE_URL, spec["id"] + ":" + topic["key"]))
            topic["seed_reference"] = execution["regression"]["seed_references"][topic["key"]]
        for query in spec["queries"]:
            query["original_split"] = query["split"]
            query["split"] = "exposed_regression"
        return {**spec, "contract": execution["contract"], "budget": execution["budget"]}
    if phase != "blind":
        raise ValueError("unknown natural retest phase")
    # Opening the sealed material is impossible before the retained regression completes.
    if engine is None:
        raise ValueError("regression must complete before opening the sealed holdout")
    require_phase_complete(engine, execution, "regression", phase_spec(execution, "regression"))
    seal = json.loads((ROOT / execution["blind_seal"]).read_text())
    directory = Path(seal["sealed_directory"])
    for row in seal["files"]:
        path = directory / row["path"]
        if (
            path.parent != directory
            or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]
        ):
            raise ValueError("sealed blind artifact changed")
    spec = json.loads((directory / "registration.json").read_text())
    refs = json.loads((directory / "seed-references-v1.json").read_text())
    for topic in spec["topics"]:
        topic["seed_reference"] = refs[topic["id"]]
    return {**spec, "contract": execution["contract"], "budget": execution["budget"]}


class RetestJournal(MemberBatchJournal):
    """Add phase caps without subtracting or reclassifying any historical physical call."""

    def __init__(
        self, engine: Engine, spec: dict[str, Any], cap: Decimal, phase_limit: int
    ) -> None:
        super().__init__(engine, spec, cap)
        self.phase_limit = phase_limit

    def extra_physical_guard(self, session: Session, context: CallContext) -> None:
        if context.lease is None or context.lease.worker != self.spec["id"]:
            raise BudgetExceeded("unregistered retest phase or task")
        if phase_request_count(session, self.spec["id"]) >= self.phase_limit:
            raise BudgetExceeded("retest phase physical request cap reached")


def refresh(
    engine: Engine, execution: dict[str, Any], phase: str, proxy: str | None
) -> dict[str, Any]:
    settings = get_settings()
    with httpx.Client(
        base_url=settings.openrouter_base_url,
        headers={"Authorization": "Bearer " + settings.openrouter_api_key},
        proxy=proxy,
        timeout=30,
    ) as client:
        provider = provider_key_status(client)
    with Session(engine) as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        state, budget = batch_state(session), budget_status(session)
        if budget["scope"] != "evaluation" or Decimal(budget["monthly_limit_usd"]) != Decimal(
            "1.50"
        ):
            raise BudgetExceeded("the original cumulative evaluation policy changed")
        holds = [
            dict(r)
            for r in session.execute(
                text(
                    "SELECT id,status,reserved_usd::text,provider_generation_id "
                    "FROM billed_requests "
                    "WHERE status IN ('reserved','usage_unknown') ORDER BY id"
                )
            ).mappings()
        ]
        expected = execution["original_holds"]
        if holds != expected or state["unresolved_ids"]:
            raise BudgetExceeded("historical holds changed or new unknown cost; reconcile first")
        remaining = provider.get("limit_remaining")
        if remaining is None:
            raise BudgetExceeded("fresh provider remaining limit is unavailable")
        known = Decimal(state["known_usd"])
        old_holds = sum((Decimal(h["reserved_usd"]) for h in holds), Decimal(0))
        future = Decimal(execution["budget"]["future_reserved_usd"])
        cap = min(
            Decimal(execution["phases"][phase]["cumulative_pool_ceiling_usd"]),
            Decimal("0.20") - future,
            known + Decimal("1.50") - Decimal(budget["accounting"]["occupancy_usd"]) - future,
            known + Decimal(str(remaining)) - old_holds - future,
        )
        if cap <= known:
            raise BudgetExceeded("no remaining retest pool after existing spend and future reserve")
        value = {
            "at": datetime.now(UTC).isoformat(),
            "phase": phase,
            "batch": state,
            "budget": budget,
            "original_holds": holds,
            "provider": {
                k: provider.get(k)
                for k in ("limit", "limit_remaining", "usage", "usage_monthly", "limit_reset")
            },
            "future_reserved_usd": str(future),
            "effective_cumulative_pool_ceiling_usd": str(cap),
            "new_credit_created": False,
        }
    return value


def seed_phase(engine: Engine, execution: dict[str, Any], spec: dict[str, Any], phase: str) -> None:
    sources = load_sources()
    with Session(engine) as session, session.begin():
        if phase == "blind":
            seal = json.loads((ROOT / execution["blind_seal"]).read_text())
            packages = json.loads((Path(seal["sealed_directory"]) / "inputs.json").read_text())
            seed_packages(session, packages["packages"], material_offset=200000)
        excluded = {item["article_id"] for item in spec.get("unavailable_inputs", [])}
        # Real current_input is required before any task is created. No readiness mutation.
        for query in spec["queries"]:
            if query["article_id"] not in excluded:
                current_input(session, query["article_id"], sources, datetime.now(UTC))
        seed_topics(session, spec, sources)


def run_phase(
    engine: Engine,
    execution: dict[str, Any],
    spec: dict[str, Any],
    phase: str,
    cap: Decimal,
    proxy: str | None,
) -> None:
    sources = load_sources()
    topic_ids = frozenset(t["id"] for t in spec["topics"])

    @contextmanager
    def scope() -> Generator[Session]:
        with Session(engine) as session, session.begin():
            yield session

    journal = RetestJournal(engine, spec, cap, execution["phases"][phase]["physical_request_limit"])
    handler = MemberHandler(
        {s.id: s for s in sources},
        scope=scope,
        topic_ids=topic_ids,
        client_factory=lambda context: LlmClient(
            context=context,
            transport=httpx.HTTPTransport(proxy=proxy) if proxy else None,
            journal_factory=lambda _: journal,
        ),
    )
    handlers: Handlers = {
        ("paid", kind): handler for kind in ("topic_recall", "topic_judge", "topic_review")
    }
    with (EVIDENCE / f"{phase}-first-run.ndjson").open("x") as output:

        def record(value: dict[str, Any]) -> None:
            output.write(
                json.dumps({"at": datetime.now(UTC).isoformat(), **value}, default=str) + "\n"
            )
            output.flush()

        record({"event": "start", "registration": spec["id"], "contract": member_contract()})
        excluded = {item["article_id"]: item for item in spec.get("unavailable_inputs", [])}
        completed_queries: list[int] = []
        for query in spec["queries"]:
            if query["article_id"] in excluded:
                record({"event": "unavailable", "input": excluded[query["article_id"]]})
                continue
            with scope() as session:
                pending = session.scalar(
                    select(PipelineTask.id)
                    .where(
                        PipelineTask.queue == "paid",
                        PipelineTask.status.in_(UNFINISHED),
                    )
                    .limit(1)
                )
                if pending is not None:
                    raise ValueError(
                        "unrelated or unfinished paid task; reconcile before continuing"
                    )
                identity = enqueue_member_processing(
                    session,
                    query["article_id"],
                    sources=sources,
                    now=datetime.now(UTC),
                    topic_ids=topic_ids,
                )
                task = session.get(PipelineTask, identity)
                assert task is not None
                snapshots = [task.payload["query"]] + [
                    a["snapshot"] for t in task.payload["topics"] for a in t["anchors"]
                ]
                versions = {fingerprint(vector_input(s)) for s in snapshots}
                warm = [key for key in versions if session.get(ContentVector, key) is not None]
                record(
                    {
                        "event": "query",
                        "article_id": query["article_id"],
                        "split": query["split"],
                        "recall_task": identity,
                        "plan": task.payload,
                        "vector_cache_before": {"unique_inputs": len(versions), "warm_keys": warm},
                    }
                )
            for _ in range(12):
                with scope() as session:
                    for task in session.scalars(
                        select(PipelineTask).where(
                            PipelineTask.status == "pending", PipelineTask.queue == "paid"
                        )
                    ):
                        task.max_attempts = 1
                if not process_one(
                    "paid", handlers, worker=spec["id"], scope=scope, lease_seconds=900
                ):
                    break
                with scope() as session:
                    tasks = phase_tasks(session, spec["id"])
                    record(
                        {
                            "event": "checkpoint",
                            "article_id": query["article_id"],
                            "tasks": [
                                {
                                    "id": t.id,
                                    "article_id": t.article_id,
                                    "kind": t.kind,
                                    "status": t.status,
                                    "result": t.result,
                                    "last_error": t.last_error,
                                }
                                for t in tasks
                            ],
                            "cost": batch_state(session),
                        }
                    )
                    state = batch_state(session)
                    reached = limits_reached(session, spec, execution, phase, cap)
                    if (
                        reached
                        or any(t.status == "budget_deferred" for t in tasks)
                        or state["unresolved_ids"]
                    ):
                        record({"event": "halt", "reason": "budget/request cap or new unknown"})
                        return
            with scope() as session:
                if (
                    session.scalar(
                        select(PipelineTask.id)
                        .where(PipelineTask.queue == "paid", PipelineTask.status.in_(UNFINISHED))
                        .limit(1)
                    )
                    is not None
                ):
                    record({"event": "halt", "reason": "query has unfinished successors"})
                    return
            completed_queries.append(query["article_id"])
        with scope() as session:
            task_ids = [t.id for t in phase_tasks(session, spec["id"])]
        record(
            {
                "event": "complete",
                "registration": spec["id"],
                "execution_fingerprint": fingerprint(execution),
                "contract": member_contract(),
                "completed_queries": completed_queries,
                "task_ids": task_ids,
            }
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("refresh", "seed", "run"))
    parser.add_argument("phase", choices=("regression", "blind"))
    parser.add_argument("--proxy")
    args = parser.parse_args()
    require_original_database()
    execution = load_execution()
    engine = get_engine()
    with engine.connect() as lock:
        if not lock.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": RUN_LOCK}):
            raise ValueError("another member evaluation process owns the original ledger")
        try:
            spec = phase_spec(execution, args.phase, engine=engine)
            if args.action == "seed":
                seed_phase(engine, execution, spec, args.phase)
                return
            if get_settings().grounding_budget_24h_usd != 1.0:
                raise ValueError("retain the explicit isolated evaluation grounding cap of 1 USD")
            load_key_from_ssh("unspun")
            reading = refresh(engine, execution, args.phase, args.proxy)
            target = EVIDENCE / f"{args.phase}-before-{args.action}.json"
            with target.open("x") as output:
                json.dump(reading, output, default=str, indent=2)
            if args.action == "run":
                get_settings().r2_member_processing_enabled = True
                run_phase(
                    engine,
                    execution,
                    spec,
                    args.phase,
                    Decimal(reading["effective_cumulative_pool_ceiling_usd"]),
                    args.proxy,
                )
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": RUN_LOCK})


if __name__ == "__main__":
    main()
