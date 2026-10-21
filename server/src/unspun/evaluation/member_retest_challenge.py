"""Explicit injected reviewer challenges, excluded from natural end-to-end quality."""

import argparse
import json
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal, cast
from uuid import UUID, uuid5

import httpx
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from unspun.core.config import get_settings
from unspun.core.content import fingerprint
from unspun.core.db import get_engine
from unspun.core.llm import LlmClient
from unspun.core.member_contracts import MemberDecision, member_contract
from unspun.core.member_models import ContentVector
from unspun.core.member_recall import current_input, topic_candidate, vector_input
from unspun.core.sources import load_sources
from unspun.core.task_models import PipelineTask
from unspun.core.tasks import Lease, enqueue
from unspun.core.topic_contracts import DefineTopic, TopicMutation
from unspun.core.topic_models import Topic
from unspun.core.topics import mutate_topic
from unspun.evaluation.member_quality import (
    RUN_LOCK,
    batch_state,
    require_original_database,
    seed_topics,
)
from unspun.evaluation.member_retest import (
    EVIDENCE,
    RetestJournal,
    limits_reached,
    load_execution,
    phase_spec,
    phase_tasks,
    refresh,
    require_phase_complete,
)
from unspun.evaluation.run_quality import load_key_from_ssh
from unspun.pipeline.member_processing import MemberHandler
from unspun.pipeline.r1_worker import Handlers, process_one


def run_challenges(
    engine: Engine, execution: dict[str, Any], cap: Decimal, proxy: str | None
) -> None:
    spec = execution["challenges"]
    spec = {**spec, "budget": execution["budget"]}
    sources = load_sources()

    @contextmanager
    def scope() -> Generator[Session]:
        with Session(engine) as session, session.begin():
            yield session

    journal = RetestJournal(
        engine, spec, cap, execution["phases"]["challenge"]["physical_request_limit"]
    )
    real = MemberHandler(
        {s.id: s for s in sources},
        scope=scope,
        client_factory=lambda context: LlmClient(
            context=context,
            transport=httpx.HTTPTransport(proxy=proxy) if proxy else None,
            journal_factory=lambda _: journal,
        ),
    )
    cases = {case["topic_id"]: case for case in spec["cases"]}

    class InjectedDecision:
        def run(self, lease: Lease) -> dict[str, Any]:
            case = cases[lease.payload["candidate"]["topic"]["id"]]
            return {
                "decision": MemberDecision.model_validate(case["decision"]).model_dump(mode="json")
            }

        def apply(self, session: Session, lease: Lease, result: Any) -> dict[str, Any]:
            return real.apply(session, lease, result)

    class ReviewWithRegisteredRace:
        def run(self, lease: Lease) -> dict[str, Any]:
            result = real.run(lease)
            case = cases[lease.payload["candidate"]["topic"]["id"]]
            if case.get("force_revision_after_review"):
                with scope() as session:
                    topic = session.get(Topic, case["topic_id"])
                    assert topic is not None
                    mutate_topic(
                        session,
                        UUID(topic.id),
                        TopicMutation(
                            mutation_id=uuid5(UUID(topic.id), "registered-after-review-race"),
                            expected_revision=topic.revision,
                            actor="registered-review-challenge",
                            reason="Registered revision race after the actual reviewer response",
                            change=DefineTopic(
                                kind=cast(Literal["event", "issue"], topic.kind),
                                title=topic.title,
                                domains=tuple(topic.domains),
                            ),
                        ),
                        sources=sources,
                        now=datetime.now(UTC),
                    )
            return result

        def apply(self, session: Session, lease: Lease, result: Any) -> dict[str, Any]:
            return real.apply(session, lease, result)

    handlers: Handlers = {
        ("paid", "topic_judge"): InjectedDecision(),
        ("paid", "topic_review"): ReviewWithRegisteredRace(),
    }
    with (EVIDENCE / "challenge-first-run.ndjson").open("x") as output:

        def record(value: dict[str, Any]) -> None:
            output.write(
                json.dumps({"at": datetime.now(UTC).isoformat(), **value}, default=str) + "\n"
            )
            output.flush()

        record({"event": "start", "registration": spec["id"], "natural_end_to_end": False})
        for case in spec["cases"]:
            with scope() as session:
                query = current_input(session, case["article_id"], sources, datetime.now(UTC))
                topic = topic_candidate(session, case["topic_id"], sources, datetime.now(UTC))
                keys = [
                    fingerprint(vector_input(s))
                    for s in [query, *(a["snapshot"] for a in topic["anchors"])]
                ]
                if any(session.get(ContentVector, key) is None for key in keys):
                    raise ValueError("challenge requires previously measured real vectors")
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
                record({"event": "injected_challenge", "case": case, "task_id": task_id})
            for _ in range(3):
                with scope() as session:
                    for task in session.scalars(
                        select(PipelineTask).where(
                            PipelineTask.queue == "paid", PipelineTask.status == "pending"
                        )
                    ):
                        task.max_attempts = 1
                if not process_one(
                    "paid", handlers, worker=spec["id"], scope=scope, lease_seconds=900
                ):
                    break
                with scope() as session:
                    tasks = phase_tasks(session, spec["id"])
                    state = batch_state(session)
                    record(
                        {
                            "event": "checkpoint",
                            "case_id": case["id"],
                            "tasks": [
                                {
                                    "id": t.id,
                                    "kind": t.kind,
                                    "status": t.status,
                                    "result": t.result,
                                    "last_error": t.last_error,
                                }
                                for t in tasks
                            ],
                            "cost": state,
                        }
                    )
                    if (
                        limits_reached(session, spec, execution, "challenge", cap)
                        or state["unresolved_ids"]
                        or any(t.status == "budget_deferred" for t in tasks)
                    ):
                        record({"event": "halt", "reason": "budget/request cap or new unknown"})
                        return
        record({"event": "complete"})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("seed", "run"))
    parser.add_argument("--proxy")
    args = parser.parse_args()
    require_original_database()
    execution = load_execution()
    engine = get_engine()
    with engine.connect() as lock:
        if not lock.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": RUN_LOCK}):
            raise ValueError("another member evaluation process owns the original ledger")
        try:
            for phase in ("regression", "blind"):
                require_phase_complete(
                    engine, execution, phase, phase_spec(execution, phase, engine=engine)
                )
            if args.action == "seed":
                with Session(engine) as session, session.begin():
                    seed_topics(session, execution["challenges"], load_sources())
                return
            load_key_from_ssh("unspun")
            reading = refresh(engine, execution, "challenge", args.proxy)
            with (EVIDENCE / "challenge-before-run.json").open("x") as output:
                json.dump(reading, output, default=str, indent=2)
            get_settings().r2_member_processing_enabled = True
            run_challenges(
                engine,
                execution,
                Decimal(reading["effective_cumulative_pool_ceiling_usd"]),
                args.proxy,
            )
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": RUN_LOCK})


if __name__ == "__main__":
    main()
