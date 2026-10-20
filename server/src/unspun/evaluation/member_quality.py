"""One frozen R2-06 real-model batch on the original cumulative evaluation ledger."""

import argparse
import hashlib
import json
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx
from sqlalchemy import Date, DateTime, Engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from unspun.core.billing import (
    PENDING,
    TOPIC_STAGE_CAPS,
    BudgetExceeded,
    CallContext,
    DatabaseJournal,
    Reservation,
    budget_status,
    reservation_bound,
)
from unspun.core.billing_admin import provider_key_status
from unspun.core.billing_models import BilledRequest, BudgetPolicy
from unspun.core.config import get_settings
from unspun.core.content import fingerprint
from unspun.core.db import get_engine
from unspun.core.llm import LlmClient
from unspun.core.member_contracts import member_contract
from unspun.core.member_recall import current_input
from unspun.core.models import Article, ContentDerivation, ContentMaterial, LlmUsage
from unspun.core.sources import Source, load_sources
from unspun.core.task_models import PipelineTask
from unspun.core.topic_contracts import DefineTopic, EvidenceRef, SetMember, TopicMutation
from unspun.core.topics import mutate_topic
from unspun.evaluation.run_quality import load_key_from_ssh
from unspun.pipeline.member_processing import MemberHandler, enqueue_member_processing
from unspun.pipeline.r1_worker import Handlers, process_one

ROOT = Path(__file__).resolve().parents[4]
EVIDENCE = ROOT / "docs/acceptance/r2-06-evaluation"
DATABASE = "unspun_quality_r1_20261016"
RUN_LOCK = 206006
RESERVE_LOCK = 206007


def registration() -> dict[str, Any]:
    manifest = json.loads((ROOT / "docs/evaluations/r2/member-freeze-v1.json").read_text())
    execution = json.loads((ROOT / "docs/evaluations/r2/member-execution-v1.json").read_text())
    availability_freeze = json.loads(
        (ROOT / "docs/evaluations/r2/member-availability-freeze-v1.json").read_text()
    )
    for item in [*manifest["files"], *execution["files"], *availability_freeze["files"]]:
        if hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("frozen member evaluation input changed")
    value = json.loads((ROOT / "docs/evaluations/r2/member-registration-v1.json").read_text())
    if value["contract"] != member_contract():
        raise ValueError("frozen member contract changed")
    availability = json.loads(
        (ROOT / "docs/evaluations/r2/member-availability-v1.json").read_text()
    )
    value["unavailable_inputs"] = availability["unavailable_inputs"]
    value["queries"] = sorted(
        [*value["queries"], *availability["additional_queries"]],
        key=lambda q: q["split"] == "holdout",
    )
    return value


def require_original_database() -> None:
    url = make_url(get_settings().database_url)
    if url.host not in ("localhost", "127.0.0.1") or url.database != DATABASE:
        raise ValueError("member evaluation must use the original local cumulative ledger")


def batch_state(session: Session) -> dict[str, Any]:
    rows = list(
        session.scalars(select(BilledRequest).where(BilledRequest.stage.in_(TOPIC_STAGE_CAPS)))
    )
    known = Decimal(
        str(
            session.scalar(
                select(func.coalesce(func.sum(LlmUsage.cost_usd), 0))
                .join(BilledRequest, BilledRequest.usage_id == LlmUsage.id)
                .where(BilledRequest.stage.in_(TOPIC_STAGE_CAPS))
            )
            or 0
        )
    )
    return {
        "physical_requests": len(rows),
        "stage_counts": {stage: sum(r.stage == stage for r in rows) for stage in TOPIC_STAGE_CAPS},
        "known_usd": str(known),
        "held_usd": str(sum((r.reserved_usd for r in rows if r.status in PENDING), Decimal(0))),
        "unknown_ids": [r.id for r in rows if r.status == "usage_unknown"],
        "unresolved_ids": [r.id for r in rows if r.status in PENDING],
        "request_ids": [r.id for r in rows],
    }


class MemberBatchJournal:
    """Persistent pooled/call ceilings, serialized before the existing journal reserves."""

    def __init__(self, engine: Engine, spec: dict[str, Any], effective_cap: Decimal) -> None:
        self.engine, self.spec, self.cap = engine, spec, effective_cap
        self.journal = DatabaseJournal(engine)

    def reserve(
        self, *, purpose: str, model: str, request: dict[str, Any], context: CallContext
    ) -> Reservation:
        # The separate advisory lock never holds the policy row while the core
        # journal opens its own short transaction. HTTP starts after both close.
        with Session(self.engine) as session, session.begin():
            session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": RESERVE_LOCK})
            if context.stage not in TOPIC_STAGE_CAPS:
                raise BudgetExceeded("member batch cannot fund another stage")
            lease = context.lease
            unavailable = {item["article_id"] for item in self.spec.get("unavailable_inputs", [])}
            if (
                lease is None
                or lease.article_id in unavailable
                or lease.article_id not in {q["article_id"] for q in self.spec["queries"]}
            ):
                raise BudgetExceeded("content is outside the frozen paid query set")
            state = batch_state(session)
            if state["unresolved_ids"]:
                raise BudgetExceeded("new unknown cost halted the member batch")
            logical = fingerprint([context.logical_key, context.phase, purpose, model, request])
            previous = session.scalar(
                select(BilledRequest).where(BilledRequest.logical_key == logical)
            )
            if previous is None or previous.status != "responded":
                budget = self.spec["budget"]
                if (
                    state["physical_requests"] >= budget["physical_request_limit"]
                    or state["stage_counts"][context.stage]
                    >= budget["stage_physical_limits"][context.stage]
                    or Decimal(state["known_usd"])
                    + Decimal(state["held_usd"])
                    + reservation_bound(model, request)
                    > self.cap
                ):
                    raise BudgetExceeded(
                        "member batch pooled budget or physical request cap reached"
                    )
            return self.journal.reserve(
                purpose=purpose, model=model, request=request, context=context
            )

    def identify(self, identity: str, generation_id: str, http_status: int) -> None:
        self.journal.identify(identity, generation_id, http_status)

    def finish(self, identity: str, data: dict[str, Any], http_status: int) -> bool:
        return self.journal.finish(identity, data, http_status)

    def unknown(self, identity: str, reason: str, http_status: int | None = None) -> None:
        self.journal.unknown(identity, reason, http_status)


def allocate(session: Session, spec: dict[str, Any], provider: dict[str, Any]) -> dict[str, Any]:
    policy = session.get(BudgetPolicy, 1, with_for_update=True)
    if policy is None or policy.scope != "evaluation" or not policy.enabled or policy.incident:
        raise ValueError("the original evaluation policy is unavailable")
    if policy.monthly_limit_usd != Decimal("1.50") or batch_state(session)["physical_requests"]:
        raise ValueError("allocation must precede this first batch without resetting prior costs")
    if (
        policy.key_fingerprint
        != hashlib.sha256(get_settings().openrouter_api_key.encode()).hexdigest()
    ):
        raise ValueError("provider key differs from the original ledger")
    before = budget_status(session)
    old_holds = Decimal(before["accounting"]["unresolved_holds_usd"])
    available = policy.monthly_limit_usd - Decimal(before["accounting"]["occupancy_usd"])
    remaining = provider.get("limit_remaining")
    if remaining is None:
        raise ValueError("a current provider remaining limit is required")
    cap = min(
        Decimal("0.20"),
        Decimal(spec["budget"]["batch_limit_usd"]),
        available,
        max(Decimal(0), Decimal(str(remaining)) - old_holds),
    )
    if cap <= 0:
        raise BudgetExceeded("no original evaluation/provider allocation remains")
    policy.stage_caps = {**policy.stage_caps, **spec["budget"]["stage_caps_usd"]}
    session.flush()
    return {
        "registered_at": datetime.now(UTC).isoformat(),
        "registration_id": spec["id"],
        "effective_cap_usd": str(cap),
        "provider": provider,
        "before": before,
        "after": budget_status(session),
        "new_credit_created": False,
        "original_unknown_holds_released": False,
    }


def temporal_values(model: Any, values: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for column in model.__table__.columns:
        if column.name not in values:
            continue
        value = values[column.name]
        if isinstance(value, str):
            if isinstance(column.type, DateTime):
                value = datetime.fromisoformat(value)
            elif isinstance(column.type, Date):
                value = date.fromisoformat(value)
        result[column.name] = value
    return result


def seed_packages(
    session: Session, packages: list[dict[str, Any]], *, exclude_ids: frozenset[int] = frozenset()
) -> None:
    """Append exact retained material/card versions; never certify excluded inputs."""
    selected = [p for p in packages if p["article"]["id"] not in exclude_ids]
    # Validate every identity before appending any object. A URL collision with
    # different material cannot be resolved by changing the old current version.
    urls = {p["article"]["url"] for p in selected}
    if (
        session.scalar(
            select(Article.id)
            .where(Article.processing_track == "r1", Article.url.in_(urls))
            .limit(1)
        )
        is not None
    ):
        raise ValueError("a frozen URL already exists; no overwrite; register an exclusion")
    if (
        session.scalar(
            select(Article.id)
            .where(Article.id.in_([p["article"]["id"] for p in selected]))
            .limit(1)
        )
        is not None
    ):
        raise ValueError("a frozen article identity already exists; no overwrite allowed")
    for package in selected:
        original = package["article"]
        if session.get(Article, original["id"]) is not None:
            raise ValueError("a frozen article identity already exists; no overwrite allowed")
        article = Article(
            **temporal_values(
                Article, {**original, "current_material_id": None, "processing_track": "r1"}
            )
        )
        session.add(article)
        session.flush()
        material = ContentMaterial(
            **temporal_values(
                ContentMaterial, {**package["material"], "id": 100000 + package["material"]["id"]}
            )
        )
        session.add(material)
        session.flush()
        article.current_material_id = material.id
        session.flush()
        for row in package["derivations"]:
            session.add(
                ContentDerivation(
                    **temporal_values(
                        ContentDerivation,
                        {**row, "id": 100000 + row["id"], "material_id": material.id},
                    )
                )
            )
        session.flush()


def seed_topics(session: Session, spec: dict[str, Any], sources: list[Source]) -> None:
    now = datetime.now(UTC)
    for topic in spec["topics"]:
        anchor = current_input(session, topic["anchors"][0], sources, now)
        domains = anchor["qualification"]["card"]["payload"]["domains"]
        identity = UUID(topic["id"])

        def write(
            revision: int, change: Any, *, identity: UUID = identity, key: str = topic["key"]
        ) -> None:
            mutate_topic(
                session,
                identity,
                TopicMutation(
                    mutation_id=uuid5(NAMESPACE_URL, f"{spec['id']}:{key}:{revision}"),
                    expected_revision=revision,
                    actor="ai-technical-evaluation-seed",
                    reason="Frozen real material seed; no model or user approval implied",
                    change=change,
                ),
                sources=sources,
                now=now,
            )

        write(0, DefineTopic(kind=topic["kind"], title=topic["title"], domains=tuple(domains)))
        content = anchor["content"]
        voice = "description" if content["scope"] == "media_description" else "reported"
        if topic["seed_relation"] == "opinion":
            voice = "author"
        write(
            1,
            SetMember(
                article_id=content["article_id"],
                material_id=content["material_id"],
                relation=topic["seed_relation"],
                basis="Frozen AI technical anchor; classification not a user label",
                decision_version=spec["id"] + ":manual-seed",
                evidence=(
                    EvidenceRef(
                        article_id=content["article_id"],
                        material_id=content["material_id"],
                        paragraph=0,
                        quote=content["paragraphs"][0]["text"][:1000],
                        voice=voice,
                    ),
                ),
            ),
        )


def run_batch(engine: Engine, spec: dict[str, Any], cap: Decimal, proxy: str | None) -> None:
    sources = load_sources()

    @contextmanager
    def scope() -> Generator[Session]:
        with Session(engine) as session, session.begin():
            yield session

    journal = MemberBatchJournal(engine, spec, cap)
    handler = MemberHandler(
        {s.id: s for s in sources},
        scope=scope,
        client_factory=lambda context: LlmClient(
            context=context,
            transport=httpx.HTTPTransport(proxy=proxy) if proxy else None,
            journal_factory=lambda _: journal,
        ),
    )
    handlers: Handlers = {
        ("paid", kind): handler for kind in ("topic_recall", "topic_judge", "topic_review")
    }
    with (EVIDENCE / "first-run.ndjson").open("x") as output:

        def record(value: dict[str, Any]) -> None:
            output.write(
                json.dumps(
                    {"at": datetime.now(UTC).isoformat(), **value}, ensure_ascii=False, default=str
                )
                + "\n"
            )
            output.flush()

        record({"event": "start", "registration": spec["id"], "contract": member_contract()})
        unavailable = {item["article_id"]: item for item in spec.get("unavailable_inputs", [])}
        for query in spec["queries"]:
            if query["article_id"] in unavailable:
                record({"event": "unavailable", "input": unavailable[query["article_id"]]})
                continue
            with scope() as session:
                identity = enqueue_member_processing(
                    session, query["article_id"], sources=sources, now=datetime.now(UTC)
                )
                task = session.get(PipelineTask, identity)
                assert task is not None
                record(
                    {
                        "event": "query",
                        "article_id": query["article_id"],
                        "split": query["split"],
                        "recall_task": identity,
                        "plan": task.payload,
                    }
                )
            for _ in range(12):
                # Preserve each first technical failure without scheduling another
                # execution attempt. The client's bounded HTTP retry still counts.
                with scope() as session:
                    for pending in session.scalars(
                        select(PipelineTask).where(
                            PipelineTask.article_id == query["article_id"],
                            PipelineTask.kind.in_(["topic_recall", "topic_judge", "topic_review"]),
                            PipelineTask.status == "pending",
                        )
                    ):
                        pending.max_attempts = 1
                if not process_one(
                    "paid", handlers, worker=spec["id"], scope=scope, lease_seconds=900
                ):
                    break
                with scope() as session:
                    tasks = list(
                        session.scalars(
                            select(PipelineTask).where(
                                PipelineTask.kind.in_(
                                    ["topic_recall", "topic_judge", "topic_review"]
                                )
                            )
                        )
                    )
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
                    failed = [t for t in tasks if t.status == "budget_deferred"]
                    if failed or batch_state(session)["unresolved_ids"]:
                        record(
                            {
                                "event": "halt",
                                "reason": "budget stop or new unknown",
                                "task_ids": [t.id for t in failed],
                            }
                        )
                        return
        record({"event": "complete"})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "allocate", "seed", "run"))
    parser.add_argument("--key-source-ssh", default="unspun")
    parser.add_argument("--proxy")
    args = parser.parse_args()
    require_original_database()
    spec = registration()
    engine = get_engine()
    with engine.connect() as lock:
        if not lock.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": RUN_LOCK}):
            raise ValueError("another member evaluation process owns the original ledger")
        try:
            if args.action == "check":
                with Session(engine) as session:
                    session.execute(text("SET TRANSACTION READ ONLY"))
                    print(
                        json.dumps(
                            {"budget": budget_status(session), "batch": batch_state(session)},
                            default=str,
                        )
                    )
                return
            if args.action in ("allocate", "run"):
                load_key_from_ssh(args.key_source_ssh)
            if args.action == "allocate":
                with (EVIDENCE / "allocation.json").open("x") as output:
                    with httpx.Client(
                        base_url=get_settings().openrouter_base_url,
                        headers={"Authorization": "Bearer " + get_settings().openrouter_api_key},
                        proxy=args.proxy,
                        timeout=30,
                    ) as client:
                        provider = provider_key_status(client)
                    safe = {
                        k: provider.get(k)
                        for k in (
                            "limit",
                            "limit_remaining",
                            "usage",
                            "usage_monthly",
                            "limit_reset",
                        )
                    }
                    with Session(engine) as session, session.begin():
                        value = allocate(session, spec, safe)
                    json.dump(value, output, default=str, ensure_ascii=False, indent=2)
            elif args.action == "seed":
                packages = json.loads(
                    (ROOT / "docs/evaluations/r2/member-inputs-v1.json").read_text()
                )
                with Session(engine) as session, session.begin():
                    seed_packages(
                        session,
                        packages["packages"],
                        exclude_ids=frozenset(
                            item["article_id"] for item in spec.get("unavailable_inputs", [])
                        ),
                    )
                    seed_topics(session, spec, load_sources())
            else:
                if get_settings().grounding_budget_24h_usd != 1.0:
                    raise ValueError("use the retained explicit evaluation grounding cap of 1 USD")
                get_settings().r2_member_processing_enabled = True
                allocation = json.loads((EVIDENCE / "allocation.json").read_text())
                run_batch(engine, spec, Decimal(allocation["effective_cap_usd"]), args.proxy)
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": RUN_LOCK})


if __name__ == "__main__":
    main()
