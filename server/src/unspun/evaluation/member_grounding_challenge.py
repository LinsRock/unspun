"""Real audit and CAS adversaries over exposed originals; never natural quality."""

import argparse
import copy
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from threading import Barrier
from typing import Any

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from unspun.core.billing import BudgetExceeded
from unspun.core.config import get_settings
from unspun.core.content import fingerprint
from unspun.core.db import get_engine
from unspun.core.member_contracts import MemberDecision, member_contract
from unspun.core.member_models import ContentVector, MemberJudgment
from unspun.core.member_recall import current_input, topic_candidate, vector_input
from unspun.core.task_models import PipelineTask
from unspun.core.tasks import Lease, claim, complete, enqueue, fail
from unspun.evaluation.member_grounding import (
    EVIDENCE,
    FREEZE,
    load_execution,
    mark_stop,
    refresh,
    require_reviewed_entry,
    runner,
    scoped_tasks,
    seed_namespace,
    sha,
    should_stop,
)
from unspun.evaluation.member_quality import ROOT, RUN_LOCK, batch_state, require_original_database
from unspun.evaluation.run_quality import load_key_from_ssh
from unspun.pipeline.r1_worker import Handlers, process_one


def challenge_spec(execution: dict[str, Any]) -> dict[str, Any]:
    ref = execution["challenge_registration"]
    if sha(ROOT / ref["path"]) != ref["sha256"]:
        raise ValueError("frozen challenge registration changed")
    return {
        **json.loads((ROOT / ref["path"]).read_text()),
        "budget": execution["budget"],
        "contract": execution["contract"],
    }


def run_challenges(
    engine: Engine, execution: dict[str, Any], spec: dict[str, Any], cap: Decimal, proxy: str | None
) -> None:
    real, scope = runner(engine, execution, spec, "challenge", cap, proxy)
    cases = {c["id"]: c for c in spec["cases"]}
    captured: dict[str, dict[str, Any]] = {}
    captured_tasks: dict[str, int] = {}
    active_case: dict[str, Any] = {}

    class Injected:
        def run(self, lease: Lease) -> dict[str, Any]:
            return {
                "decision": MemberDecision.model_validate(active_case["decision"]).model_dump(
                    mode="json"
                )
            }

        def apply(self, session: Session, lease: Lease, result: Any) -> dict[str, Any]:
            return real.apply(session, lease, result)

    class ActualOrReplay:
        def run(self, lease: Lease) -> dict[str, Any]:
            replay = active_case.get("replay_actual_review_from")
            if replay:
                if replay not in captured:
                    raise ValueError("the registered actual-review source did not complete")
                return copy.deepcopy(captured[replay])
            result = real.run(lease)
            captured[active_case["id"]] = copy.deepcopy(result)
            captured_tasks[active_case["id"]] = lease.task_id
            return result

        def apply(self, session: Session, lease: Lease, result: Any) -> dict[str, Any]:
            return real.apply(session, lease, result)

    handlers: Handlers = {
        ("paid", "topic_judge"): Injected(),
        ("paid", "topic_review"): ActualOrReplay(),
    }
    with (EVIDENCE / "challenge-first-run.ndjson").open("x") as output:

        def record(value: dict[str, Any]) -> None:
            output.write(
                json.dumps({"at": datetime.now(UTC).isoformat(), **value}, default=str) + "\n"
            )
            output.flush()

        def guard() -> bool:
            with scope() as session:
                stopped = should_stop(session, execution, spec, "challenge", cap)
                if stopped:
                    state = batch_state(session)
                    record(
                        {"event": "halt", "reason": "budget/request/unknown guard", "batch": state}
                    )
                    mark_stop("challenge", "budget/request/unknown guard", state)
                return stopped

        def inject(case: dict[str, Any]) -> int | None:
            active_case.clear()
            active_case.update(case)
            with scope() as session:
                query = current_input(session, case["article_id"], real.sources, datetime.now(UTC))
                topic = topic_candidate(session, case["topic_id"], real.sources, datetime.now(UTC))
                keys = [
                    fingerprint(vector_input(s))
                    for s in [query, *[a["snapshot"] for a in topic["anchors"]]]
                ]
                if any(session.get(ContentVector, key) is None for key in keys):
                    raise ValueError(
                        "challenge requires retained real vectors; no fabricated cache"
                    )
                packet = {
                    "query": query,
                    "candidate": {"topic": topic, "vectors": keys},
                    "contract": member_contract(),
                }
                task_id = enqueue(
                    session,
                    queue="paid",
                    kind="topic_judge",
                    object_key="content:" + str(query["content"]["article_id"]),
                    article_id=query["content"]["article_id"],
                    source_id=query["content"]["source_id"],
                    input_fingerprint=fingerprint(packet),
                    strategy_version=str(member_contract()["version"]),
                    payload=packet,
                )
                task = session.get(PipelineTask, task_id)
                assert task
                task.max_attempts = 1
                record(
                    {
                        "event": "injected_challenge",
                        "case": case,
                        "task_id": task_id,
                        "packet": packet,
                        "natural_end_to_end": False,
                    }
                )
            process_one(
                "paid",
                handlers,
                worker=spec["id"],
                scope=scope,
                lease_seconds=900,
                task_ids=frozenset({task_id}),
            )
            with scope() as session:
                task = session.get(PipelineTask, task_id)
                assert task
                review_ids = [
                    t.id
                    for t in scoped_tasks(session, spec)
                    if t.kind == "topic_review"
                    and t.payload["decision_key"] == task.input_fingerprint
                ]
                for identity in review_ids:
                    row = session.get(PipelineTask, identity)
                    assert row
                    row.max_attempts = 1
                record(
                    {
                        "event": "injected_result",
                        "case_id": case["id"],
                        "status": task.status,
                        "last_error": task.last_error,
                        "review_task_ids": review_ids,
                    }
                )
                return review_ids[0] if review_ids else None

        def finish_review(case: dict[str, Any], identity: int) -> None:
            active_case.clear()
            active_case.update(case)
            process_one(
                "paid",
                handlers,
                worker=spec["id"],
                scope=scope,
                lease_seconds=900,
                task_ids=frozenset({identity}),
            )
            with scope() as session:
                task = session.get(PipelineTask, identity)
                assert task
                row = session.get(MemberJudgment, task.payload["decision_key"])
                assert row
                record(
                    {
                        "event": "actual_review_result",
                        "case_id": case["id"],
                        "task_id": identity,
                        "task_status": task.status,
                        "status": row.status,
                        "review": row.review,
                        "revision": row.applied_revision,
                        "last_error": task.last_error,
                        "replayed_from_review_task": captured_tasks.get(
                            case.get("replay_actual_review_from", "")
                        ),
                        "natural_end_to_end": False,
                        "cost": batch_state(session),
                    }
                )

        record(
            {
                "event": "start",
                "registration": spec["id"],
                "natural_end_to_end": False,
                "execution_fingerprint": fingerprint(execution),
                "source_freeze_sha256": sha(FREEZE),
            }
        )
        for case in spec["cases"]:
            if case.get("cas_competition_group"):
                continue
            if guard():
                return
            identity = inject(case)
            if identity is not None:
                finish_review(case, identity)
            if guard():
                return
        # Both real reviews complete before two independent DB connections race to apply.
        held: list[tuple[Lease, dict[str, Any]]] = []
        for key in ("cas-race-a", "cas-race-b"):
            if guard():
                return
            case = cases[key]
            identity = inject(case)
            if identity is None:
                record({"event": "race_unmeasured", "reason": "injected control failed"})
                return
            with scope() as session:
                lease = claim(
                    session,
                    queue="paid",
                    kinds={"topic_review"},
                    worker=spec["id"],
                    lease_seconds=900,
                    task_ids=frozenset({identity}),
                )
                assert lease
            try:
                result = real.run(lease)
            except BudgetExceeded as error:
                with scope() as session:
                    fail(
                        session,
                        lease,
                        error=str(error),
                        retry_at=error.retry_at,
                        disposition="budget",
                    )
                for earlier, result in held:
                    with scope() as session:
                        complete(
                            session,
                            earlier,
                            apply=lambda db, held_lease=earlier, held_result=result: real.apply(
                                db, held_lease, held_result
                            ),
                        )
                record(
                    {
                        "event": "race_unmeasured",
                        "reason": "budget stopped review; CAS competition remains unmeasured",
                    }
                )
                guard()
                return
            except Exception as error:
                with scope() as session:
                    fail(session, lease, error=type(error).__name__ + ": " + str(error))
                for earlier, result in held:
                    with scope() as session:
                        complete(
                            session,
                            earlier,
                            apply=lambda db, held_lease=earlier, held_result=result: real.apply(
                                db, held_lease, held_result
                            ),
                        )
                record(
                    {
                        "event": "race_unmeasured",
                        "reason": "real control review failed",
                        "error": str(error),
                    }
                )
                return
            held.append((lease, result))
            record(
                {
                    "event": "actual_review_held_for_cas_race",
                    "case_id": key,
                    "task_id": identity,
                    "result": result,
                }
            )
        barrier = Barrier(2)

        def apply_one(item: tuple[Lease, dict[str, Any]]) -> bool:
            lease, result = item
            barrier.wait(timeout=10)
            with scope() as session:
                return complete(session, lease, apply=lambda db: real.apply(db, lease, result))

        with ThreadPoolExecutor(max_workers=2) as pool:
            receipts = list(pool.map(apply_one, held))
        with scope() as session:
            rows = [session.get(MemberJudgment, lease.payload["decision_key"]) for lease, _ in held]
            record(
                {
                    "event": "actual_cas_competition",
                    "accepted_task_completions": receipts,
                    "statuses": [r.status if r else None for r in rows],
                    "revisions": [r.applied_revision if r else None for r in rows],
                    "task_ids": [lease.task_id for lease, _ in held],
                    "natural_end_to_end": False,
                }
            )
        if guard():
            return
        record({"event": "complete", "registration": spec["id"], "natural_end_to_end": False})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("seed", "refresh", "run"))
    parser.add_argument("--proxy")
    args = parser.parse_args()
    require_original_database()
    execution = load_execution()
    require_reviewed_entry(execution)
    engine = get_engine()
    spec = challenge_spec(execution)
    with engine.connect() as lock:
        if not lock.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": RUN_LOCK}):
            raise ValueError("another evaluation owns the original ledger")
        try:
            if (EVIDENCE / "paid-stop.json").exists():
                raise BudgetExceeded("all paid phases remain stopped")
            if args.action == "seed":
                seed_namespace(engine, spec)
                return
            key = load_key_from_ssh("unspun")
            if not key:
                raise ValueError("original provider credential unavailable")
            os.environ["UNSPUN_OPENROUTER_API_KEY"] = key
            os.environ["UNSPUN_GROUNDING_BUDGET_24H_USD"] = "1.00"
            os.environ["UNSPUN_R2_MEMBER_PROCESSING_ENABLED"] = "true"
            get_settings.cache_clear()
            reading = refresh(engine, execution, "challenge", args.proxy)
            with (EVIDENCE / ("challenge-before-" + args.action + ".json")).open("x") as out:
                json.dump(reading, out, indent=2, default=str)
            if args.action == "run":
                run_challenges(
                    engine,
                    execution,
                    spec,
                    Decimal(reading["effective_cumulative_pool_ceiling_usd"]),
                    args.proxy,
                )
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": RUN_LOCK})


if __name__ == "__main__":
    main()
