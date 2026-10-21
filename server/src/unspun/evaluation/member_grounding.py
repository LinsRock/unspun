"""Cumulative v4 grounding validation on new namespaces, never rewriting old runs."""

import argparse
import gzip
import hashlib
import json
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from unspun.core.billing import BudgetExceeded, CallContext, budget_status
from unspun.core.billing_admin import provider_key_status
from unspun.core.billing_models import BilledRequest, BudgetPolicy
from unspun.core.config import get_settings
from unspun.core.content import fingerprint
from unspun.core.db import get_engine
from unspun.core.llm import LlmClient, parse_json_content
from unspun.core.member_contracts import MemberDecision, MemberReview, member_contract
from unspun.core.member_evidence import review_supported
from unspun.core.member_models import ContentVector, MemberJudgment
from unspun.core.member_recall import current_input, vector_input
from unspun.core.models import Article, ContentDerivation, ContentMaterial
from unspun.core.sources import load_sources
from unspun.core.task_models import PipelineTask
from unspun.evaluation.member_quality import (
    ROOT,
    RUN_LOCK,
    batch_state,
    require_original_database,
    seed_packages,
    seed_topics,
    temporal_values,
)
from unspun.evaluation.member_retest import RetestJournal, phase_request_count
from unspun.evaluation.run_quality import load_key_from_ssh
from unspun.pipeline.member_processing import MemberHandler, enqueue_member_processing
from unspun.pipeline.r1_worker import Handlers, process_one

EVIDENCE = ROOT / "docs/acceptance/r2-06-grounding"
EXECUTION = ROOT / "docs/evaluations/r2/member-grounding-budget-v1.json"
FREEZE = ROOT / "docs/evaluations/r2/member-grounding-freeze-v2.json"
UNFINISHED = {"pending", "running", "retry_wait", "budget_deferred"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_execution() -> dict[str, Any]:
    value = json.loads(EXECUTION.read_text())
    if value["contract"] != member_contract():
        raise ValueError("grounding execution contract changed")
    for row in json.loads(FREEZE.read_text())["files"]:
        if sha(ROOT / row["path"]) != row["sha256"]:
            raise ValueError("frozen grounding source or registration changed")
    ref = value["exposed_registration"]
    if sha(ROOT / ref["path"]) != ref["sha256"]:
        raise ValueError("exposed registration changed")
    return value


def exposed_spec(execution: dict[str, Any]) -> dict[str, Any]:
    spec = json.loads((ROOT / execution["exposed_registration"]["path"]).read_text())
    return {**spec, "budget": execution["budget"], "contract": execution["contract"]}


def scoped_tasks(session: Session, spec: dict[str, Any]) -> list[PipelineTask]:
    ids = sorted(t["id"] for t in spec["topics"])
    return [
        task
        for task in session.scalars(
            select(PipelineTask)
            .where(PipelineTask.strategy_version == str(member_contract()["version"]))
            .order_by(PipelineTask.id)
        )
        if (task.kind == "topic_recall" and task.payload.get("trace", {}).get("topic_scope") == ids)
        or task.payload.get("candidate", {}).get("topic", {}).get("id") in ids
    ]


def require_exact_inputs(session: Session, spec: dict[str, Any]) -> None:
    """Reuse only exact historical versions; no readiness changes, backfill or old task resume."""
    excluded = {row["article_id"] for row in spec.get("unavailable_inputs", [])}
    required = {q["article_id"] for q in spec["queries"] if q["article_id"] not in excluded}
    required.update(a for t in spec["topics"] for a in t["anchors"])
    seen: set[int] = set()
    for source in spec["input_sources"]:
        path = ROOT / source["path"]
        if sha(path) != source["sha256"]:
            raise ValueError("exposed original input artifact changed")
        data = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
        offset = source["material_offset"]
        for package in json.loads(data)["packages"]:
            identity = package["article"]["id"]
            if identity not in required:
                continue
            article = session.get(Article, identity, populate_existing=True)
            expected = temporal_values(
                Article,
                {
                    **package["article"],
                    "current_material_id": offset + package["material"]["id"],
                    "processing_track": "r1",
                },
            )
            if article is None or any(
                getattr(article, key) != val for key, val in expected.items()
            ):
                raise ValueError("exposed article differs from its exact retained version")
            for model, rows in (
                (ContentMaterial, [package["material"]]),
                (ContentDerivation, package["derivations"]),
            ):
                for original in rows:
                    fixed = {**original, "id": offset + original["id"]}
                    if model is ContentDerivation:
                        fixed["material_id"] = offset + package["material"]["id"]
                    expected = temporal_values(model, fixed)
                    row = session.get(model, fixed["id"], populate_existing=True)
                    if row is None or any(
                        getattr(row, key) != val for key, val in expected.items()
                    ):
                        raise ValueError(
                            "exposed material or qualification differs from the original"
                        )
            current_input(session, identity, load_sources(), datetime.now(UTC))
            seen.add(identity)
    if seen != required:
        raise ValueError(
            "exposed registered input is unavailable; do not manufacture qualification"
        )


def require_reviewed_entry(execution: dict[str, Any]) -> None:
    proof = json.loads((EVIDENCE / "paid-entry-review-proof-v2.json").read_text())
    if not (
        proof["source_freeze_sha256"] == sha(FREEZE)
        and proof["execution_fingerprint"] == fingerprint(execution)
        and proof["pr_ci_passed"] is True
        and proof["main_ci_checked"] is True
        and proof["runtime_deployment_verified"] is True
        and proof["local_evaluation_sources_frozen"] is True
        and proof["deployed_runtime_source_hashes_match"] is True
        and proof["production_enabled"] is False
    ):
        raise ValueError(
            "reviewed entry, CI, deployed source or disabled-production proof is missing"
        )


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
        holds = [
            dict(row)
            for row in session.execute(
                text(
                    "SELECT id,status,reserved_usd::text,provider_generation_id "
                    "FROM billed_requests "
                    "WHERE status IN ('reserved','usage_unknown') ORDER BY id"
                )
            ).mappings()
        ]
        if (
            budget["scope"] != "evaluation"
            or Decimal(budget["monthly_limit_usd"]) != Decimal("1.50")
            or holds != execution["original_holds"]
            or state["unresolved_ids"]
        ):
            raise BudgetExceeded(
                "original allocation/holds changed or new unknown; stop and reconcile"
            )
        remaining = provider.get("limit_remaining")
        if remaining is None:
            raise BudgetExceeded("fresh provider remaining limit unavailable")
        known = Decimal(state["known_usd"])
        future = Decimal(execution["budget"]["future_reserved_usd"])
        old_holds = sum((Decimal(h["reserved_usd"]) for h in holds), Decimal(0))
        cap = min(
            Decimal(execution["budget"]["batch_limit_usd"]) - future,
            Decimal(execution["phases"][phase]["cumulative_pool_ceiling_usd"]),
            known + Decimal("1.50") - Decimal(budget["accounting"]["occupancy_usd"]) - future,
            known + Decimal(str(remaining)) - old_holds - future,
        )
        if cap <= known:
            raise BudgetExceeded("no remaining authorized pool after fees and all reservations")
        return {
            "at": datetime.now(UTC).isoformat(),
            "phase": phase,
            "batch": state,
            "budget": budget,
            "original_holds": holds,
            "provider": provider,
            "future_reserved_usd": str(future),
            "effective_cumulative_pool_ceiling_usd": str(cap),
            "same_original_pool_revised_to_usd": "0.30",
            "old_fees_reset": False,
        }


def allocate(engine: Engine, execution: dict[str, Any]) -> dict[str, Any]:
    require_reviewed_entry(execution)
    with Session(engine) as session, session.begin():
        state = batch_state(session)
        policy = session.get(BudgetPolicy, 1, with_for_update=True)
        budget = execution["budget"]
        if (
            policy is None
            or policy.scope != "evaluation"
            or not policy.enabled
            or policy.incident
            or policy.monthly_limit_usd != Decimal("1.50")
            or state["physical_requests"] != budget["previous_physical_requests"]
            or abs(Decimal(state["known_usd"]) - Decimal(budget["previous_spend_usd"]))
            > Decimal("0.0000000001")
            or state["unresolved_ids"]
            or policy.stage_caps != budget["previous_stage_caps_usd"]
        ):
            raise ValueError(
                "only the registered original policy and accumulated fees may be revised"
            )
        before = {
            "scope": policy.scope,
            "monthly_limit_usd": str(policy.monthly_limit_usd),
            "stage_caps": dict(policy.stage_caps),
            "version": policy.version,
        }
        policy.stage_caps = dict(budget["stage_caps_usd"])
        after = {**before, "stage_caps": dict(policy.stage_caps)}
        return {
            "at": datetime.now(UTC).isoformat(),
            "before": before,
            "after": after,
            "pool_before_usd": "0.20",
            "pool_after_usd": "0.30",
            "batch": state,
            "original_unknown_holds_unchanged": True,
            "fees_or_reservations_reset": False,
            "registered_policy_row_only": True,
            "production_changed": False,
        }


def seed_namespace(engine: Engine, spec: dict[str, Any]) -> None:
    with Session(engine) as session, session.begin():
        require_exact_inputs(session, spec)
        if scoped_tasks(session, spec):
            raise ValueError("namespace already has tasks; no overwrite or automatic repeat")
        seed_topics(session, spec, load_sources())


class GroundingJournal(RetestJournal):
    def __init__(
        self,
        engine: Engine,
        spec: dict[str, Any],
        execution: dict[str, Any],
        phase: str,
        cap: Decimal,
    ) -> None:
        super().__init__(engine, spec, cap, execution["phases"][phase]["physical_request_limit"])
        self.execution = execution

    def extra_physical_guard(self, session: Session, context: CallContext) -> None:
        if (EVIDENCE / "paid-stop.json").exists() or session.scalar(
            select(PipelineTask.id)
            .where(
                PipelineTask.strategy_version == str(member_contract()["version"]),
                PipelineTask.status == "budget_deferred",
            )
            .limit(1)
        ) is not None:
            raise BudgetExceeded("grounding paid work already stopped; no later phase may continue")
        for phase, limits in self.execution["phases"].items():
            worker = self.execution["id"] + ":" + phase
            if phase_request_count(session, worker) >= limits["physical_request_limit"]:
                raise BudgetExceeded("a grounding phase reached its physical cap; stop all phases")
        super().extra_physical_guard(session, context)


def mark_stop(phase: str, reason: str, state: dict[str, Any]) -> None:
    path = EVIDENCE / "paid-stop.json"
    if not path.exists():
        with path.open("x") as stream:
            json.dump(
                {
                    "at": datetime.now(UTC).isoformat(),
                    "phase": phase,
                    "reason": reason,
                    "batch": state,
                    "all_paid_phases_stopped": True,
                },
                stream,
                indent=2,
            )


def runner(
    engine: Engine,
    execution: dict[str, Any],
    spec: dict[str, Any],
    phase: str,
    cap: Decimal,
    proxy: str | None,
) -> tuple[MemberHandler, Any]:
    @contextmanager
    def scope() -> Generator[Session]:
        with Session(engine) as session, session.begin():
            yield session

    journal = GroundingJournal(engine, spec, execution, phase, cap)
    handler = MemberHandler(
        {s.id: s for s in load_sources()},
        scope=scope,
        topic_ids=frozenset(t["id"] for t in spec["topics"]),
        client_factory=lambda context: LlmClient(
            context=context,
            transport=httpx.HTTPTransport(proxy=proxy) if proxy else None,
            journal_factory=lambda _: journal,
        ),
    )
    return handler, scope


def should_stop(
    session: Session, execution: dict[str, Any], spec: dict[str, Any], phase: str, cap: Decimal
) -> bool:
    state, budget = batch_state(session), execution["budget"]
    return bool(
        (EVIDENCE / "paid-stop.json").exists()
        or state["unresolved_ids"]
        or Decimal(state["known_usd"]) + Decimal(state["held_usd"]) >= cap
        or state["physical_requests"] >= budget["physical_request_limit"]
        or phase_request_count(session, spec["id"])
        >= execution["phases"][phase]["physical_request_limit"]
        or any(state["stage_counts"][k] >= v for k, v in budget["stage_physical_limits"].items())
        or any(t.status == "budget_deferred" for t in scoped_tasks(session, spec))
    )


def run_exposed(
    engine: Engine,
    execution: dict[str, Any],
    spec: dict[str, Any],
    cap: Decimal,
    proxy: str | None,
    *,
    phase: str = "exposed",
) -> None:
    handler, scope = runner(engine, execution, spec, phase, cap, proxy)
    handlers: Handlers = {
        ("paid", kind): handler for kind in ("topic_recall", "topic_judge", "topic_review")
    }
    topic_ids = frozenset(t["id"] for t in spec["topics"])
    with (EVIDENCE / f"{phase}-first-run.ndjson").open("x") as output:

        def record(value: dict[str, Any]) -> None:
            output.write(
                json.dumps({"at": datetime.now(UTC).isoformat(), **value}, default=str) + "\n"
            )
            output.flush()

        record(
            {
                "event": "start",
                "registration": spec["id"],
                "contract": member_contract(),
                "execution_fingerprint": fingerprint(execution),
                "source_freeze_sha256": sha(FREEZE),
            }
        )
        excluded = {q["article_id"]: q for q in spec.get("unavailable_inputs", [])}
        completed: list[int] = []
        for query in spec["queries"]:
            if query["article_id"] in excluded:
                record({"event": "unavailable", "input": excluded[query["article_id"]]})
                continue
            with scope() as session:
                if should_stop(session, execution, spec, phase, cap):
                    record({"event": "halt", "reason": "budget/request/unknown guard"})
                    mark_stop(phase, "budget/request/unknown guard", batch_state(session))
                    return
                if any(t.status in UNFINISHED for t in scoped_tasks(session, spec)):
                    raise ValueError("this namespace has unfinished tasks; no repeat")
                identity = enqueue_member_processing(
                    session,
                    query["article_id"],
                    sources=handler.sources,
                    now=datetime.now(UTC),
                    topic_ids=topic_ids,
                )
                task = session.get(PipelineTask, identity)
                assert task
                versions = {
                    fingerprint(vector_input(s))
                    for s in [
                        task.payload["query"],
                        *[a["snapshot"] for t in task.payload["topics"] for a in t["anchors"]],
                    ]
                }
                warm = [k for k in versions if session.get(ContentVector, k) is not None]
                record(
                    {
                        "event": "query",
                        "article_id": query["article_id"],
                        "recall_task": identity,
                        "plan": task.payload,
                        "vector_cache_before": {"unique_inputs": len(versions), "warm_keys": warm},
                    }
                )
            for _ in range(12):
                with scope() as session:
                    tasks = scoped_tasks(session, spec)
                    for task in tasks:
                        if task.status == "pending":
                            task.max_attempts = 1
                    ids = frozenset(t.id for t in tasks)
                if not process_one(
                    "paid",
                    handlers,
                    worker=spec["id"],
                    scope=scope,
                    lease_seconds=900,
                    task_ids=ids,
                ):
                    break
                with scope() as session:
                    record(
                        {
                            "event": "checkpoint",
                            "article_id": query["article_id"],
                            "tasks": [
                                {
                                    "id": t.id,
                                    "kind": t.kind,
                                    "status": t.status,
                                    "result": t.result,
                                    "last_error": t.last_error,
                                }
                                for t in scoped_tasks(session, spec)
                            ],
                            "cost": batch_state(session),
                        }
                    )
                    if should_stop(session, execution, spec, phase, cap):
                        record({"event": "halt", "reason": "budget/request/unknown guard"})
                        mark_stop(phase, "budget/request/unknown guard", batch_state(session))
                        return
            with scope() as session:
                if any(t.status in UNFINISHED for t in scoped_tasks(session, spec)):
                    record({"event": "halt", "reason": "unfinished successors"})
                    return
            completed.append(query["article_id"])
        with scope() as session:
            ids = [t.id for t in scoped_tasks(session, spec)]
        record(
            {
                "event": "complete",
                "registration": spec["id"],
                "completed_queries": completed,
                "task_ids": ids,
                "contract": member_contract(),
                "execution_fingerprint": fingerprint(execution),
            }
        )


def verify_exposed_database(
    session: Session, execution: dict[str, Any], gate: dict[str, Any]
) -> None:
    spec = exposed_spec(execution)
    records = [
        json.loads(line)
        for line in (EVIDENCE / "exposed-first-run.ndjson").read_text().splitlines()
    ]
    excluded = {q["article_id"] for q in spec.get("unavailable_inputs", [])}
    expected_queries = [q["article_id"] for q in spec["queries"] if q["article_id"] not in excluded]
    final = records[-1]
    tasks = scoped_tasks(session, spec)
    if not (
        final.get("event") == "complete"
        and final.get("execution_fingerprint") == fingerprint(execution)
        and final.get("contract") == member_contract()
        and final.get("completed_queries") == expected_queries
        and final.get("task_ids") == [t.id for t in tasks]
    ):
        raise ValueError("exposed gate does not match the complete frozen DB run")
    names = {t["id"]: t["key"] for t in spec["topics"]}
    queries = {q["article_id"]: q for q in spec["queries"]}
    judges = {t.id: t for t in tasks if t.kind == "topic_judge"}
    expected_pairs = {
        (q["article_id"], key)
        for q in spec["queries"]
        if q["article_id"] not in excluded
        for key in q["expected_associations"]
    }
    reached = {
        (t.article_id, names[t.payload["candidate"]["topic"]["id"]]) for t in judges.values()
    }
    first: dict[int, BilledRequest] = {}
    for bill in session.scalars(
        select(BilledRequest)
        .where(BilledRequest.task_id.in_(judges), BilledRequest.stage == "topic_judgment")
        .order_by(BilledRequest.started_at, BilledRequest.id)
    ):
        assert bill.task_id is not None
        first.setdefault(bill.task_id, bill)
    associated = correct = 0
    for identity, bill in first.items():
        try:
            raw = parse_json_content(
                (bill.response_payload or {})["choices"][0]["message"]["content"]
            )
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        if raw.get("certainty") == "certain" and raw.get("classification") != "independent":
            associated += 1
            task = judges[identity]
            allowed = queries[task.article_id]["expected_associations"].get(
                names[task.payload["candidate"]["topic"]["id"]], []
            )
            correct += raw.get("classification") in allowed
    applied = list(
        session.scalars(
            select(MemberJudgment).where(
                MemberJudgment.task_id.in_(judges), MemberJudgment.status == "applied"
            )
        )
    )
    findings = gate["strict_basis_findings"]
    if {r["judgment_fingerprint"] for r in findings} != {r.input_fingerprint for r in applied}:
        raise ValueError("strict basis review must cover every actual applied decision")
    supported = invalid = 0
    for row in applied:
        finding = next(r for r in findings if r["judgment_fingerprint"] == row.input_fingerprint)
        allowed = queries[row.article_id]["expected_associations"].get(names[row.topic_id], [])
        decision = MemberDecision.model_validate(row.decision)
        good = bool(
            row.review
            and review_supported(
                row.input_snapshot, decision, MemberReview.model_validate(row.review)
            )
            and decision.classification in allowed
            and finding["fully_supported"] is True
            and not finding["issues"]
        )
        supported += good
        invalid += not good
    counts = {
        "candidate_recall": (len(expected_pairs.intersection(reached)), len(expected_pairs)),
        "judgment_precision": (correct, associated),
        "strict_supported_final_coverage": (supported, len(expected_pairs)),
        "all_invalid_applied": (invalid, len(applied)),
    }
    for name, (numerator, denominator) in counts.items():
        if (gate["metrics"][name]["numerator"], gate["metrics"][name]["denominator"]) != (
            numerator,
            denominator,
        ):
            raise ValueError(
                "exposed gate metric differs from original first outputs or DB receipts"
            )
        value = numerator / denominator if denominator else None
        if gate["metrics"][name]["value"] != value:
            raise ValueError("exposed gate ratio is inconsistent with its real denominator")
    challenges = EVIDENCE / "challenge-first-run.ndjson"
    if sha(challenges) != gate["challenge_first_output_sha256"]:
        raise ValueError("challenge first-output evidence changed")
    challenge_records = [json.loads(line) for line in challenges.read_text().splitlines()]
    if not (
        challenge_records[-1].get("event") == "complete"
        and challenge_records[0].get("execution_fingerprint") == fingerprint(execution)
        and any(
            r.get("event") == "actual_cas_competition"
            and sorted(r["statuses"]) == ["applied", "stale"]
            for r in challenge_records
        )
    ):
        raise ValueError("required real challenges or complete CAS competition did not complete")
    challenge_spec = json.loads((ROOT / execution["challenge_registration"]["path"]).read_text())
    for case in challenge_spec["cases"]:
        if case.get("cas_competition_group"):
            continue
        event = "injected_result" if case["expected_status"] == "failed" else "actual_review_result"
        matches = [
            r
            for r in challenge_records
            if r.get("event") == event and r.get("case_id") == case["id"]
        ]
        if len(matches) != 1 or matches[0]["status"] != case["expected_status"]:
            raise ValueError("an actual registered review challenge failed its frozen expectation")


def require_exposed_pass(engine: Engine, execution: dict[str, Any]) -> None:
    gate_path = EVIDENCE / "exposed-gate.json"
    if not gate_path.exists():
        raise ValueError("exposed gates must pass before opening any fresh blind artifact")
    gate = json.loads(gate_path.read_text())
    if not (
        gate["exposed_numeric_and_strict_basis_pass"] is True
        and gate["metrics"]["candidate_recall"]["value"] is not None
        and gate["metrics"]["candidate_recall"]["value"] >= 0.90
        and gate["metrics"]["judgment_precision"]["value"] is not None
        and gate["metrics"]["judgment_precision"]["value"] >= 0.95
        and gate["metrics"]["strict_supported_final_coverage"]["value"] is not None
        and gate["metrics"]["strict_supported_final_coverage"]["value"] >= 0.80
        and gate["metrics"]["all_invalid_applied"]["numerator"] == 0
        and gate["real_challenges_pass"] is True
        and gate["strict_basis_review_complete"] is True
        and gate["source_freeze_sha256"] == sha(FREEZE)
        and gate["execution_fingerprint"] == fingerprint(execution)
        and gate["first_output_sha256"] == sha(EVIDENCE / "exposed-first-run.ndjson")
    ):
        raise ValueError("exposed gates must pass before any fresh blind preparation or paid run")
    spec = exposed_spec(execution)
    with Session(engine) as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        verify_exposed_database(session, execution, gate)
        if any(t.status in UNFINISHED for t in scoped_tasks(session, spec)):
            raise ValueError("exposed namespace remains unfinished")
        if should_stop(
            session, execution, spec, "exposed", Decimal(execution["budget"]["batch_limit_usd"])
        ):
            raise BudgetExceeded("paid batch already stopped; blind entry cannot continue")


def blind_spec(engine: Engine, execution: dict[str, Any]) -> dict[str, Any]:
    # This gate runs before opening the seal, private directory, input or label files.
    require_exposed_pass(engine, execution)
    seal_path = ROOT / execution["new_blind_seal"]
    seal = json.loads(seal_path.read_text())
    proof = json.loads((EVIDENCE / "blind-entry-review-proof.json").read_text())
    if not (
        seal["source_freeze_sha256"] == sha(FREEZE)
        and seal["execution_fingerprint"] == fingerprint(execution)
        and seal["exposed_gate_sha256"] == sha(EVIDENCE / "exposed-gate.json")
        and proof["seal_sha256"] == sha(seal_path)
        and proof["pr_ci_passed"] is True
        and proof["registration_merged"] is True
        and seal["contract"] == member_contract()
    ):
        raise ValueError("new blind seal and separate reviewed registration are not bound")
    directory = Path(seal["sealed_directory"])
    for row in seal["files"]:
        path = directory / row["path"]
        if path.parent != directory or sha(path) != row["sha256"]:
            raise ValueError("new blind sealed artifact changed")
    spec = json.loads((directory / "registration.json").read_text())
    if spec["id"] != execution["id"] + ":blind":
        raise ValueError("blind worker must use the pre-registered cumulative namespace")
    return {
        **spec,
        "contract": execution["contract"],
        "budget": execution["budget"],
        "sealed_inputs": str(directory / "inputs.json"),
    }


def seed_blind(engine: Engine, spec: dict[str, Any]) -> None:
    packages = json.loads(Path(spec["sealed_inputs"]).read_text())["packages"]
    with Session(engine) as session, session.begin():
        seed_packages(session, packages, material_offset=300000)
        for query in spec["queries"]:
            current_input(session, query["article_id"], load_sources(), datetime.now(UTC))
        if any("seed_reference" not in topic for topic in spec["topics"]):
            raise ValueError("new blind seed references must be explicitly sealed")
        seed_topics(session, spec, load_sources())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=("refresh", "allocate", "seed", "run", "check-blind-gate")
    )
    parser.add_argument("--proxy")
    parser.add_argument("--phase", choices=("exposed", "blind"), default="exposed")
    args = parser.parse_args()
    require_original_database()
    execution = load_execution()
    engine = get_engine()
    with engine.connect() as lock:
        if not lock.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": RUN_LOCK}):
            raise ValueError("another evaluation owns the original ledger")
        try:
            if args.action == "check-blind-gate":
                require_exposed_pass(engine, execution)
                return
            if (
                args.action in {"seed", "run", "allocate"}
                and (EVIDENCE / "paid-stop.json").exists()
            ):
                raise BudgetExceeded("all paid grounding work remains stopped")
            if args.action == "seed":
                if args.phase == "blind":
                    seed_blind(engine, blind_spec(engine, execution))
                else:
                    seed_namespace(engine, exposed_spec(execution))
                return
            if args.action != "refresh":
                require_reviewed_entry(execution)
            load_key_from_ssh("unspun")
            key = get_settings().openrouter_api_key
            if not key:
                raise ValueError("original provider credential is unavailable")
            get_settings.cache_clear()
            import os

            os.environ["UNSPUN_OPENROUTER_API_KEY"] = key
            os.environ["UNSPUN_GROUNDING_BUDGET_24H_USD"] = "1.00"
            get_settings.cache_clear()
            phase = args.phase
            spec = exposed_spec(execution) if phase == "exposed" else blind_spec(engine, execution)
            reading = refresh(engine, execution, phase, args.proxy)
            with (EVIDENCE / (phase + "-before-" + args.action + ".json")).open("x") as output:
                json.dump(reading, output, indent=2, default=str)
            if args.action == "allocate":
                value = allocate(engine, execution)
                with (EVIDENCE / "allocation.json").open("x") as output:
                    json.dump(value, output, indent=2)
            elif args.action == "run":
                os.environ["UNSPUN_R2_MEMBER_PROCESSING_ENABLED"] = "true"
                get_settings.cache_clear()
                run_exposed(
                    engine,
                    execution,
                    spec,
                    Decimal(reading["effective_cumulative_pool_ceiling_usd"]),
                    args.proxy,
                    phase=phase,
                )
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": RUN_LOCK})


if __name__ == "__main__":
    main()
