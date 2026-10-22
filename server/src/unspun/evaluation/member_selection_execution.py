"""Finite v6 continuation on the retained R2-06 ledger; preparation is offline.

The registration is a proposal, not paid authority. Detached review, explicit
user authorization and a genuinely reconciled stopped request are required
before credentials, provider access, namespace writes or worker execution.
This entry never reconciles fees, allocates credit or opens a blind artifact.
"""

import argparse
import copy
import hashlib
import json
import os
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from typing import Any, TextIO, cast

import httpx
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from unspun.core.billing import BudgetExceeded, CallContext, budget_status, usd
from unspun.core.billing_admin import provider_key_status
from unspun.core.billing_models import BilledRequest, BudgetPolicy
from unspun.core.config import get_settings
from unspun.core.content import fingerprint
from unspun.core.db import get_engine
from unspun.core.llm import LlmClient, LlmError, parse_json_content
from unspun.core.member_contracts import (
    MemberDecision,
    MemberReview,
    member_contract,
    project_classification,
)
from unspun.core.member_evidence import review_supported
from unspun.core.member_models import ContentVector, MemberJudgment
from unspun.core.member_recall import current_input, topic_candidate, vector_input
from unspun.core.models import LlmUsage
from unspun.core.sources import load_sources
from unspun.core.task_models import PipelineTask
from unspun.core.tasks import Lease, claim, complete, enqueue, fail
from unspun.evaluation.member_grounding import require_exact_inputs, scoped_tasks, sha
from unspun.evaluation.member_quality import DATABASE, ROOT, RUN_LOCK, batch_state, seed_topics
from unspun.evaluation.member_retest import RetestJournal, phase_request_count
from unspun.pipeline.member_processing import MemberHandler, enqueue_member_processing
from unspun.pipeline.r1_worker import Handlers, SessionScope, process_one

DEFAULT_REGISTRATION = ROOT / "docs/evaluations/r2/member-selection-execution-v1.json"
UNFINISHED = {"pending", "running", "retry_wait", "budget_deferred"}


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError("evidence must be a JSON object")
    return cast(dict[str, Any], value)


def referenced(root: Path, ref: dict[str, Any]) -> Path:
    path = (root / ref["path"]).resolve()
    if not path.is_relative_to(root.resolve()) or sha(path) != ref["sha256"]:
        raise ValueError("registered evidence is missing, changed or outside the workspace")
    return path


@dataclass(frozen=True)
class Entry:
    root: Path
    registration: Path
    execution: dict[str, Any]
    specs: dict[str, dict[str, Any]]

    @property
    def evidence(self) -> Path:
        return self.root / self.execution["evidence_directory"]

    @property
    def stop(self) -> Path:
        return self.evidence / "paid-stop.json"

    def first_output(self, phase: str) -> Path:
        return self.evidence / f"{phase}-first-run.ndjson"


def load_entry(path: Path = DEFAULT_REGISTRATION, *, root: Path = ROOT) -> Entry:
    """Read only registered exposed evidence; no settings, DB or provider access."""
    execution = read_json(path)
    if execution["schema_version"] != "r206-selection-execution-v1":
        raise ValueError("a separately registered v6 execution is required")
    if execution["provider_reads"] != {
        "base_url": "https://openrouter.ai/api/v1",
        "method": "GET",
        "path": "/key",
        "maximum_per_authorized_phase": 1,
        "generation_lookups": 0,
        "retries": 0,
    }:
        raise ValueError("provider reads must retain the single registered account lookup")
    contract = read_json(referenced(root, execution["frozen_contract"]))["contract"]
    if execution["contract"] != contract or contract["version"] != "r2-member-v6":
        raise ValueError("execution is not the frozen v6 contract")
    for ref in execution["protected_artifacts"]:
        referenced(root, ref)
    historical = read_json(referenced(root, execution["previous_execution"]))
    budget = execution["budget"]
    for key in (
        "batch_limit_usd",
        "physical_request_limit",
        "stage_physical_limits",
        "stage_caps_usd",
        "original_evaluation_limit_usd",
        "future_reserved_usd",
        "grounding_budget_24h_usd",
        "full_reservation_algorithm_unchanged",
    ):
        if budget[key] != historical["budget"][key]:
            raise ValueError("original cumulative allocation or physical limits changed")
    stop = read_json(referenced(root, execution["previous_stop"]))
    if (
        budget["previous_physical_requests"] != 139
        or Decimal(budget["previous_spend_usd"]) != Decimal("0.07734293")
        or budget["previous_stage_counts"] != stop["batch"]["stage_counts"]
        or execution["original_holds"] != historical["original_holds"]
        or not stop["all_paid_phases_stopped"]
    ):
        raise ValueError("the retained stopped ledger baseline changed")
    for phase, limits in execution["phases"].items():
        if phase not in {"exposed", "challenge"} or any(
            limits[k] != historical["phases"][phase][k]
            for k in ("physical_request_limit", "cumulative_pool_ceiling_usd")
        ):
            raise ValueError("only the original bounded exposed and challenge phases are allowed")
    specs = {
        phase: {
            **read_json(referenced(root, execution[phase + "_registration"])),
            "budget": budget,
            "contract": contract,
        }
        for phase in ("exposed", "challenge")
    }
    original = read_json(referenced(root, historical["exposed_registration"]))
    exposed = specs["exposed"]
    if (
        exposed["queries"] != original["queries"]
        or exposed["unavailable_inputs"] != original["unavailable_inputs"]
        or exposed["technical_gates"] != original["technical_gates"]
        or exposed["input_sources"] != original["input_sources"]
        or len(exposed["topics"]) != len(original["topics"])
    ):
        raise ValueError("original labels, splits, denominators or exposed inputs changed")
    for new, old in zip(exposed["topics"], original["topics"], strict=True):
        if new["id"] == old["id"] or {k: v for k, v in new.items() if k != "id"} != {
            k: v for k, v in old.items() if k != "id"
        }:
            raise ValueError("only new topic identities may differ from the exposed registration")
    all_ids = [t["id"] for spec in specs.values() for t in spec["topics"]]
    if len(set(all_ids)) != len(all_ids):
        raise ValueError("natural and injected topic namespaces must be separate")
    evidence = (root / execution["evidence_directory"]).resolve()
    if not evidence.is_relative_to((root / "docs/evaluations/r2").resolve()):
        raise ValueError("continuation evidence must use its new evaluation directory")
    return Entry(root, path, execution, specs)


def preparation(entry: Entry) -> dict[str, Any]:
    spec = entry.specs["exposed"]
    return {
        "status": "prepared_unreviewed_not_authorized",
        "execution_fingerprint": fingerprint(entry.execution),
        "contract": entry.execution["contract"],
        "registered_queries": len(spec["queries"]),
        "executable_queries": len(spec["queries"]) - len(spec["unavailable_inputs"]),
        "expected_pairs": sum(len(q["expected_associations"]) for q in spec["queries"]),
        "challenge_cases": len(entry.specs["challenge"]["cases"]),
        "challenge_maximum_new_physical_audits": entry.specs["challenge"][
            "maximum_new_physical_audits"
        ],
        "historical_phase_requests": {
            p: v["previous_physical_requests"] for p, v in entry.execution["phases"].items()
        },
        "remaining_phase_requests": {
            p: v["physical_request_limit"] - v["previous_physical_requests"]
            for p, v in entry.execution["phases"].items()
        },
        "prior_paid_calls": 139,
        "prior_known_usd": "0.07734293",
        "retained_new_hold_usd": "0.029746",
        "retained_original_seven_holds_usd": "0.484867",
        "requirements": [
            "Detached review of exact v6 execution, source freeze and challenge expectations",
            "Authentic per-request provider receipt for the stopped R2-06 request",
            "Separately authorized reconciliation reflected in the original ledger",
            "Separate explicit user authorization bound to that review and receipt",
        ],
        "old_stop_preserved": True,
        "paid_calls": 0,
        "provider_lookups": 0,
        "database_access": False,
        "new_blind_prepared_or_read": False,
        "semantic_credit": False,
        "user_acceptance": None,
    }


def require_authority(
    entry: Entry, review_path: Path | None, authorization_path: Path | None, phase: str
) -> dict[str, Any]:
    """Validate detached evidence before any credentials, DB access or writes.

    These files record actual external review and user instruction; the entry has
    no command that creates them. Hashes establish binding, not authenticity.
    The reviewer must verify provenance of the saved instruction/provider reply.
    """
    if review_path is None or authorization_path is None:
        raise ValueError("review, genuine receipt and separate explicit paid authorization missing")
    review, authorization = read_json(review_path), read_json(authorization_path)
    execution = entry.execution
    if not (
        review["schema_version"] == "r206-selection-entry-review-v1"
        and review["execution_fingerprint"] == fingerprint(execution)
        and review["reviewer"]
        and review["reviewed_at"]
        and all(
            review[k] is True
            for k in (
                "source_freeze_reviewed",
                "challenge_expectations_reviewed",
                "pr_ci_passed",
                "main_ci_checked",
                "runtime_deployment_verified",
                "deployed_member_sources_match",
                "provider_receipt_provenance_verified",
            )
        )
        and review["production_enabled"] is False
    ):
        raise ValueError(
            "current-contract source, execution, receipt and deployment review missing"
        )
    referenced(entry.root, review["review_evidence"])
    frozen = read_json(referenced(entry.root, review["source_freeze"]))
    required = set(execution["required_source_paths"])
    if {ref["path"] for ref in frozen["files"]} != required:
        raise ValueError("review source freeze does not cover exactly the registered runtime")
    for ref in frozen["files"]:
        referenced(entry.root, ref)
    receipt_path = referenced(entry.root, review["provider_receipt"])
    receipt = read_json(receipt_path)
    data = receipt.get("data", {})
    stopped = execution["stopped_request"]
    if data.get("id") != stopped["provider_generation_id"] or usd(data.get("total_cost")) is None:
        raise ValueError("stopped request has no genuine matching per-request cost receipt")
    settlement = read_json(referenced(entry.root, review["reconciliation_authorization"]))
    if not (
        settlement.get("request_id") == stopped["id"]
        and settlement.get("provider_receipt_sha256") == sha(receipt_path)
        and settlement.get("action") == "reconcile_identified_request_only"
        and settlement.get("authorized_by")
    ):
        raise ValueError("reconciliation requires its own recorded authorization")
    referenced(entry.root, settlement["user_instruction"])
    if not (
        authorization["schema_version"] == "r206-selection-paid-authorization-v1"
        and authorization["execution_fingerprint"] == fingerprint(execution)
        and authorization["review_sha256"] == sha(review_path)
        and authorization["provider_receipt_sha256"] == sha(receipt_path)
        and authorization["action"] == "run_registered_phases_once"
        and phase in authorization["phases"]
        and set(authorization["phases"]) <= {"exposed", "challenge"}
        and authorization["authorized_by"]
        and authorization["explicit_paid_authorization"] is True
        and authorization["provider_read_authorized"] is True
        and authorization["same_cumulative_pool_usd"] == "0.30"
        and authorization["original_evaluation_limit_usd"] == "1.50"
        and datetime.fromisoformat(authorization["expires_at"]) > datetime.now(UTC)
    ):
        raise ValueError("separate explicit bounded paid authorization is missing or expired")
    referenced(entry.root, authorization["user_instruction"])
    return data


def require_ledger(session: Session, entry: Entry, provider_receipt: dict[str, Any]) -> None:
    """Read-only continuity check; reconciliation is never performed here."""
    execution = entry.execution
    policy = session.get(BudgetPolicy, 1)
    if not (
        policy
        and policy.enabled
        and not policy.incident
        and policy.scope == "evaluation"
        and policy.monthly_limit_usd == Decimal("1.50")
        and policy.stage_caps == execution["budget"]["stage_caps_usd"]
    ):
        raise ValueError("original enabled evaluation allocation or stage ceilings changed")
    holds = [
        {
            "id": r.id,
            "status": r.status,
            "reserved_usd": str(r.reserved_usd),
            "provider_generation_id": r.provider_generation_id,
        }
        for r in session.scalars(
            select(BilledRequest)
            .where(BilledRequest.status.in_(("reserved", "usage_unknown")))
            .order_by(BilledRequest.id)
        )
    ]
    if holds != execution["original_holds"]:
        raise ValueError("original holds changed or a stopped/new request remains unresolved")
    stopped = execution["stopped_request"]
    row = session.get(BilledRequest, stopped["id"])
    usage = session.get(LlmUsage, row.usage_id) if row and row.usage_id else None
    if not (
        row
        and usage
        and row.status in {"responded", "settled_without_result"}
        and row.provider_generation_id == stopped["provider_generation_id"]
        and row.reserved_usd == Decimal(stopped["reserved_usd"])
        and row.request_fingerprint == stopped["request_fingerprint"]
        and row.reconciliation
        and row.reconciliation.get("provider") == provider_receipt
        and fingerprint(row.reconciliation.get("original_response"))
        == stopped["original_response_fingerprint"]
        and abs(Decimal(str(usage.cost_usd)) - Decimal(str(provider_receipt["total_cost"])))
        < Decimal("0.0000000001")
    ):
        raise ValueError("genuine receipt is not reconciled on the original stopped request")
    state = batch_state(session)
    old_stop = read_json(referenced(entry.root, execution["previous_stop"]))
    if not set(old_stop["batch"]["request_ids"]) <= set(state["request_ids"]):
        raise ValueError("an original physical request was removed or replaced")
    old_rows = list(
        session.scalars(
            select(BilledRequest).where(BilledRequest.id.in_(old_stop["batch"]["request_ids"]))
        )
    )
    known = Decimal(0)
    for old in old_rows:
        usage = session.get(LlmUsage, old.usage_id) if old.usage_id is not None else None
        if usage is not None:
            known += Decimal(str(usage.cost_usd))
    expected = Decimal("0.07734293") + Decimal(str(provider_receipt["total_cost"]))
    if (
        len(old_rows) != 139
        or abs(known - expected) > Decimal("0.0000000001")
        or {
            stage: sum(r.stage == stage for r in old_rows)
            for stage in execution["budget"]["previous_stage_counts"]
        }
        != execution["budget"]["previous_stage_counts"]
    ):
        raise ValueError("historical physical count or cumulative fees changed")
    if state["unresolved_ids"]:
        raise BudgetExceeded("unresolved R2-06 costs stop every continuation phase")


def phase_count(session: Session, entry: Entry, phase: str) -> int:
    limits = entry.execution["phases"][phase]
    historical = phase_request_count(session, "r206-grounding-v1:" + phase)
    if historical != limits["previous_physical_requests"]:
        raise BudgetExceeded("historical phase request count changed")
    return historical + phase_request_count(session, entry.specs[phase]["id"])


def stop_reason(session: Session, entry: Entry, phase: str, cap: Decimal) -> str | None:
    state, budget = batch_state(session), entry.execution["budget"]
    if entry.stop.exists():
        return "continuation already stopped; no phase may resume"
    if state["unresolved_ids"]:
        return "new unknown or active unresolved cost"
    if Decimal(state["known_usd"]) + Decimal(state["held_usd"]) >= cap:
        return "cumulative monetary ceiling reached"
    if state["physical_requests"] >= budget["physical_request_limit"] or any(
        state["stage_counts"][stage] >= limit
        for stage, limit in budget["stage_physical_limits"].items()
    ):
        return "cumulative physical ceiling reached"
    for name, limits in entry.execution["phases"].items():
        if phase_count(session, entry, name) >= limits["physical_request_limit"]:
            return "a phase physical ceiling reached"
        if any(
            t.status == "budget_deferred" or "BudgetExceeded" in (t.last_error or "")
            for t in scoped_tasks(session, entry.specs[name])
        ):
            return "a phase budget guard stopped its candidate"
    return None


def mark_stop(entry: Entry, phase: str, reason: str, state: dict[str, Any]) -> None:
    if not entry.stop.exists():
        with entry.stop.open("x") as stream:
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


class SelectionJournal(RetestJournal):
    def __init__(self, engine: Engine, entry: Entry, phase: str, cap: Decimal) -> None:
        super().__init__(
            engine,
            entry.specs[phase],
            cap,
            entry.execution["phases"][phase]["physical_request_limit"],
        )
        self.entry, self.phase = entry, phase

    def extra_physical_guard(self, session: Session, context: CallContext) -> None:
        reason = stop_reason(session, self.entry, self.phase, self.cap)
        if reason:
            raise BudgetExceeded(reason)
        if context.lease is not None:
            task = session.get(PipelineTask, context.lease.task_id)
            if task is None or task.max_attempts != 1 or task.attempts != 1:
                raise BudgetExceeded("a candidate cannot receive another execution attempt")
            rows = list(
                session.scalars(select(BilledRequest).where(BilledRequest.task_id == task.id))
            )
            maximum = {"topic_judgment": 1, "topic_review": 4}.get(context.stage)
            if context.stage == "topic_review" and self.phase == "challenge":
                matches = [
                    c
                    for c in self.spec["cases"]
                    if c["article_id"] == task.article_id
                    and c["topic_id"] == task.payload["candidate"]["topic"]["id"]
                ]
                if len(matches) != 1:
                    raise BudgetExceeded("review is outside its registered challenge candidate")
                maximum = matches[0]["physical_audit_limit"]
            if maximum is not None and len(rows) >= maximum:
                raise BudgetExceeded("candidate physical judgment/audit ceiling reached")
        super().extra_physical_guard(session, context)

    def reserve(self, **kwargs: Any) -> Any:
        try:
            return super().reserve(**kwargs)
        except BudgetExceeded as error:
            with Session(self.engine) as session:
                mark_stop(self.entry, self.phase, str(error), batch_state(session))
            raise

    def unknown(self, identity: str, reason: str, http_status: int | None = None) -> None:
        super().unknown(identity, reason, http_status)
        with Session(self.engine) as session:
            mark_stop(self.entry, self.phase, reason, batch_state(session))


def runner(
    engine: Engine, entry: Entry, phase: str, cap: Decimal, proxy: str | None
) -> tuple[MemberHandler, SessionScope]:
    @contextmanager
    def scope() -> Generator[Session]:
        with Session(engine) as session, session.begin():
            yield session

    journal = SelectionJournal(engine, entry, phase, cap)
    return MemberHandler(
        {s.id: s for s in load_sources()},
        scope=scope,
        topic_ids=frozenset(t["id"] for t in entry.specs[phase]["topics"]),
        client_factory=lambda context: LlmClient(
            context=context,
            transport=httpx.HTTPTransport(proxy=proxy) if proxy else None,
            journal_factory=lambda _: journal,
        ),
    ), scope


def record(output: TextIO, **value: Any) -> None:
    output.write(json.dumps({"at": datetime.now(UTC).isoformat(), **value}, default=str) + "\n")
    output.flush()


def guard(engine: Engine, entry: Entry, phase: str, cap: Decimal, output: TextIO) -> bool:
    with Session(engine) as session:
        reason = stop_reason(session, entry, phase, cap)
        if reason:
            state = batch_state(session)
            record(output, event="halt", reason=reason, batch=state)
            mark_stop(entry, phase, reason, state)
        return reason is not None


def run_exposed(engine: Engine, entry: Entry, cap: Decimal, proxy: str | None) -> None:
    spec = entry.specs["exposed"]
    handler, scope = runner(engine, entry, "exposed", cap, proxy)
    handlers: Handlers = {
        ("paid", k): handler for k in ("topic_recall", "topic_judge", "topic_review")
    }
    with entry.first_output("exposed").open("x") as output:
        record(
            output,
            event="start",
            execution_fingerprint=fingerprint(entry.execution),
            registration=spec["id"],
            contract=entry.execution["contract"],
        )
        excluded = {q["article_id"]: q for q in spec["unavailable_inputs"]}
        completed: list[int] = []
        expected = [q["article_id"] for q in spec["queries"] if q["article_id"] not in excluded]

        def finish() -> None:
            with scope() as session:
                ids = [t.id for t in scoped_tasks(session, spec)]
            record(
                output,
                event="complete",
                completed_queries=completed,
                task_ids=ids,
                execution_fingerprint=fingerprint(entry.execution),
                registration=spec["id"],
            )

        for query in spec["queries"]:
            if query["article_id"] in excluded:
                record(output, event="unavailable", input=excluded[query["article_id"]])
                continue
            if guard(engine, entry, "exposed", cap, output):
                return
            with scope() as session:
                if any(t.status in UNFINISHED for t in scoped_tasks(session, spec)):
                    raise ValueError("namespace has unfinished tasks; no repeat or repair")
                identity = enqueue_member_processing(
                    session,
                    query["article_id"],
                    sources=handler.sources,
                    now=datetime.now(UTC),
                    topic_ids=frozenset(t["id"] for t in spec["topics"]),
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
                record(
                    output,
                    event="query",
                    article_id=query["article_id"],
                    recall_task=identity,
                    plan=task.payload,
                    vector_cache_before={
                        "unique_inputs": len(versions),
                        "warm_keys": sorted(k for k in versions if session.get(ContentVector, k)),
                    },
                )
            stopped = False
            for _ in range(9):  # One recall, four candidates and at most four review tasks.
                if guard(engine, entry, "exposed", cap, output):
                    stopped = True
                    break
                with scope() as session:
                    ids = frozenset(t.id for t in scoped_tasks(session, spec))
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
                        output,
                        event="checkpoint",
                        article_id=query["article_id"],
                        tasks=[
                            {
                                "id": t.id,
                                "kind": t.kind,
                                "status": t.status,
                                "result": t.result,
                                "last_error": t.last_error,
                            }
                            for t in scoped_tasks(session, spec)
                        ],
                        batch=batch_state(session),
                    )
            stopped = stopped or guard(engine, entry, "exposed", cap, output)
            with scope() as session:
                observed = scoped_tasks(session, spec)
                if any(t.status in UNFINISHED for t in observed):
                    if stopped:
                        return
                    raise ValueError(
                        "bounded query left unfinished successors; no automatic resume"
                    )
                if stopped and (
                    batch_state(session)["unresolved_ids"]
                    or any(t.status == "blocked" for t in observed)
                ):
                    return
            completed.append(query["article_id"])
            if stopped:
                if completed == expected:
                    finish()
                return
        finish()


def run_challenges(engine: Engine, entry: Entry, cap: Decimal, proxy: str | None) -> None:
    """Inject registered v6 decisions; only actual audits/CAS earn challenge evidence."""
    spec = entry.specs["challenge"]
    real, scope = runner(engine, entry, "challenge", cap, proxy)
    active: dict[str, Any] = {}
    captured: dict[str, dict[str, Any]] = {}

    class Injected:
        def run(self, lease: Lease) -> dict[str, Any]:
            return {
                "decision": MemberDecision.model_validate(active["decision"]).model_dump(
                    mode="json"
                )
            }

        def apply(self, session: Session, lease: Lease, result: Any) -> dict[str, Any]:
            return real.apply(session, lease, result)

    class Review:
        def run(self, lease: Lease) -> dict[str, Any]:
            source = active.get("replay_actual_review_from")
            if source:
                if source not in captured:
                    raise ValueError("registered real review source did not complete")
                return copy.deepcopy(captured[source])
            result = real.run(lease)
            captured[active["id"]] = copy.deepcopy(result)
            return result

        def apply(self, session: Session, lease: Lease, result: Any) -> dict[str, Any]:
            return real.apply(session, lease, result)

    handlers: Handlers = {("paid", "topic_judge"): Injected(), ("paid", "topic_review"): Review()}
    with entry.first_output("challenge").open("x") as output:
        record(
            output,
            event="start",
            execution_fingerprint=fingerprint(entry.execution),
            registration=spec["id"],
            natural_end_to_end=False,
        )

        def inject(case: dict[str, Any]) -> int | None:
            active.clear()
            active.update(case)
            with scope() as session:
                query = current_input(session, case["article_id"], real.sources, datetime.now(UTC))
                topic = topic_candidate(session, case["topic_id"], real.sources, datetime.now(UTC))
                keys = [
                    fingerprint(vector_input(s))
                    for s in [query, *[a["snapshot"] for a in topic["anchors"]]]
                ]
                if any(session.get(ContentVector, key) is None for key in keys):
                    raise ValueError(
                        "challenge requires retained genuine vectors; no synthetic cache"
                    )
                packet = {
                    "query": query,
                    "candidate": {"topic": topic, "vectors": keys},
                    "contract": member_contract(),
                }
                identity = enqueue(
                    session,
                    queue="paid",
                    kind="topic_judge",
                    object_key="content:" + str(case["article_id"]),
                    article_id=case["article_id"],
                    source_id=query["content"]["source_id"],
                    input_fingerprint=fingerprint(packet),
                    strategy_version=str(member_contract()["version"]),
                    payload=packet,
                    max_attempts=1,
                )
                record(
                    output,
                    event="injected_challenge",
                    case_id=case["id"],
                    task_id=identity,
                    packet=packet,
                    decision=case["decision"],
                    natural_end_to_end=False,
                )
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
                row = session.get(MemberJudgment, task.input_fingerprint)
                reviews = [
                    t.id
                    for t in scoped_tasks(session, spec)
                    if t.kind == "topic_review"
                    and t.payload.get("decision_key") == task.input_fingerprint
                ]
                record(
                    output,
                    event="injected_result",
                    case_id=case["id"],
                    status=task.status,
                    decision_status=row.status if row else None,
                    last_error=task.last_error,
                    review_task_ids=reviews,
                )
                return reviews[0] if reviews else None

        for case in spec["cases"]:
            if case.get("cas_competition_group"):
                continue
            if guard(engine, entry, "challenge", cap, output):
                return
            identity = inject(case)
            if identity is not None:
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
                        output,
                        event="actual_review_result",
                        case_id=case["id"],
                        task_id=identity,
                        status=row.status,
                        task_status=task.status,
                        review=row.review,
                        revision=row.applied_revision,
                        last_error=task.last_error,
                        replayed_from=case.get("replay_actual_review_from"),
                        natural_end_to_end=False,
                    )
            if guard(engine, entry, "challenge", cap, output):
                return

        held: list[tuple[Lease, dict[str, Any]]] = []
        for case in [c for c in spec["cases"] if c.get("cas_competition_group")]:
            if guard(engine, entry, "challenge", cap, output):
                return
            identity = inject(case)
            if identity is None:
                record(output, event="race_unmeasured", reason="registered control failed")
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
                review = MemberReview.model_validate(result["review"])
                with scope() as session:
                    row = session.get(MemberJudgment, lease.payload["decision_key"])
                    assert row
                    if not review_supported(
                        lease.payload, MemberDecision.model_validate(row.decision), review
                    ):
                        raise ValueError("CAS control did not receive four supported real audits")
            except Exception as error:
                with scope() as session:
                    fail(session, lease, error=str(error))
                    for earlier, _ in held:
                        fail(session, earlier, error="CAS competition incomplete; no retry")
                if isinstance(error, BudgetExceeded):
                    with scope() as session:
                        mark_stop(entry, "challenge", str(error), batch_state(session))
                record(output, event="race_unmeasured", reason=str(error))
                return
            held.append((lease, result))
            record(
                output,
                event="actual_review_held_for_cas_race",
                case_id=case["id"],
                task_id=identity,
                result=result,
            )
        if len(held) != 2:
            raise ValueError("exactly two distinct-query CAS controls are required")
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
                output,
                event="actual_cas_competition",
                accepted_task_completions=receipts,
                statuses=[r.status if r else None for r in rows],
                task_ids=[lease.task_id for lease, _ in held],
                natural_end_to_end=False,
            )
        record(output, event="complete", registration=spec["id"], natural_end_to_end=False)
        # A final allowed call can complete the evidence and exhaust the ceiling.
        # Preserve that completion while fencing every subsequent paid phase.
        guard(engine, entry, "challenge", cap, output)


def metrics(
    session: Session, entry: Entry, findings: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Original first-label denominators; missing independent basis review earns no credit."""
    spec = entry.specs["exposed"]
    tasks = reported_tasks(session, entry)
    names = {t["id"]: t["key"] for t in spec["topics"]}
    excluded = {q["article_id"] for q in spec["unavailable_inputs"]}
    queries = {q["article_id"]: q for q in spec["queries"] if q["article_id"] not in excluded}
    expected = {(i, key) for i, q in queries.items() for key in q["expected_associations"]}
    judges = {t.id: t for t in tasks if t.kind == "topic_judge"}
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
    associated = correct = schema_valid = 0
    for identity, bill in first.items():
        try:
            content = (bill.response_payload or {})["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                continue
            raw = parse_json_content(content)
        except (KeyError, IndexError, TypeError, ValueError, LlmError):
            continue
        label = project_classification(raw)
        task = judges[identity]
        allowed = queries[task.article_id]["expected_associations"].get(
            names[task.payload["candidate"]["topic"]["id"]], []
        )
        if raw.get("certainty") == "certain" and label not in (None, "independent"):
            associated += 1
            correct += label in allowed
        try:
            MemberDecision.model_validate(raw)
            schema_valid += 1
        except ValueError:
            pass
    applied = list(
        session.scalars(
            select(MemberJudgment).where(
                MemberJudgment.task_id.in_(judges), MemberJudgment.status == "applied"
            )
        )
    )
    if findings is not None and not (
        findings.get("execution_fingerprint") == fingerprint(entry.execution)
        and findings.get("first_output_sha256") == sha(entry.first_output("exposed"))
        and findings.get("reviewer")
        and findings.get("reviewed_at")
    ):
        raise ValueError("strict basis findings must bind the exact retained first run")
    reviewed = {
        v["judgment_fingerprint"]: v for v in (findings or {}).get("strict_basis_findings", [])
    }
    complete_review = bool(findings) and set(reviewed) == {r.input_fingerprint for r in applied}
    supported = invalid = 0
    for row in applied:
        finding = reviewed.get(row.input_fingerprint, {})
        decision = MemberDecision.model_validate(row.decision)
        allowed = queries[row.article_id]["expected_associations"].get(names[row.topic_id], [])
        good = bool(
            row.applied_revision
            and row.review
            and review_supported(
                row.input_snapshot, decision, MemberReview.model_validate(row.review)
            )
            and decision.classification in allowed
            and finding.get("fully_supported") is True
            and finding.get("issues") == []
        )
        supported += good
        invalid += bool(finding) and not good

    def ratio(n: int, d: int) -> dict[str, Any]:
        return {"numerator": n, "denominator": d, "value": n / d if d else None}

    return {
        "candidate_recall": ratio(len(expected & reached), len(expected)),
        "judgment_precision": ratio(correct, associated),
        "schema_valid_first_physical_attempts": ratio(schema_valid, len(first)),
        "strict_supported_final_coverage": ratio(supported, len(expected)),
        "invalid_reviewed_applied": ratio(invalid, len(applied)),
        "unreviewed_applied": len(applied)
        - len(set(reviewed) & {r.input_fingerprint for r in applied}),
        "strict_basis_review_complete": complete_review,
        "registered_queries": len(spec["queries"]),
        "executable_queries": len(queries),
        "started_queries": len({t.article_id for t in tasks if t.kind == "topic_recall"}),
        "unavailable_inputs": spec["unavailable_inputs"],
        "natural_quality_only": True,
        "user_acceptance": None,
    }


def challenge_report(session: Session, entry: Entry) -> dict[str, Any]:
    path = entry.first_output("challenge")
    if not path.exists():
        return {"status": "unmeasured", "pass": False, "natural_quality_credit": False}
    events = [json.loads(line) for line in path.read_text().splitlines()]
    if events[0].get("execution_fingerprint") != fingerprint(entry.execution):
        raise ValueError("challenge first output belongs to another registration")
    results: list[dict[str, Any]] = []
    for case in entry.specs["challenge"]["cases"]:
        if case.get("cas_competition_group"):
            continue
        injected = next(
            (
                e
                for e in events
                if e.get("event") == "injected_result" and e.get("case_id") == case["id"]
            ),
            None,
        )
        event = next(
            (
                e
                for e in events
                if e.get("event") == "actual_review_result" and e.get("case_id") == case["id"]
            ),
            None,
        )
        passed = bool(injected and injected["status"] == case["expected_status"])
        if event:
            task = session.get(PipelineTask, event["task_id"])
            row = session.get(MemberJudgment, task.payload["decision_key"]) if task else None
            passed = bool(
                row and row.status == case["expected_status"] and row.review == event["review"]
            )
            if case["expected_boundary"] == "semantic":
                passed = bool(
                    passed
                    and row
                    and row.review
                    and any(
                        check["target"] == case["rejection_target"]
                        and check["status"] in {"unsupported", "uncertain"}
                        for audit in row.review["audits"]
                        for check in audit["checks"]
                    )
                )
        results.append(
            {
                "case_id": case["id"],
                "pass": passed,
                "observed_status": event["status"]
                if event
                else injected["status"]
                if injected
                else "unmeasured",
            }
        )
    race = next((e for e in events if e.get("event") == "actual_cas_competition"), None)
    race_pass = False
    if race:
        rows: list[MemberJudgment] = []
        for identity in race["task_ids"]:
            task = session.get(PipelineTask, identity)
            row = session.get(MemberJudgment, task.payload["decision_key"]) if task else None
            if row:
                rows.append(row)
        race_pass = len(rows) == 2 and sorted(r.status for r in rows) == ["applied", "stale"]
    return {
        "cases": results,
        "actual_cas_competition_pass": race_pass,
        "pass": any(e.get("event") == "complete" for e in events)
        and race_pass
        and all(r["pass"] for r in results),
        "natural_quality_credit": False,
    }


def run_report(
    session: Session, entry: Entry, findings: dict[str, Any] | None = None
) -> dict[str, Any]:
    result = metrics(session, entry, findings)
    first = entry.first_output("exposed")
    events = [json.loads(line) for line in first.read_text().splitlines()] if first.exists() else []
    if events and events[0].get("execution_fingerprint") != fingerprint(entry.execution):
        raise ValueError("natural first output belongs to another registration")
    tasks = reported_tasks(session, entry)
    chains: list[dict[str, Any]] = []
    for event in (e for e in events if e.get("event") == "query"):
        query_tasks = [t for t in tasks if t.article_id == event["article_id"]]
        ids = [t.id for t in query_tasks]
        bills = list(session.scalars(select(BilledRequest).where(BilledRequest.task_id.in_(ids))))
        known = Decimal(0)
        for bill in bills:
            usage = session.get(LlmUsage, bill.usage_id) if bill.usage_id is not None else None
            if usage:
                known += Decimal(str(usage.cost_usd))
        applied = session.scalar(
            select(MemberJudgment)
            .where(MemberJudgment.task_id.in_(ids), MemberJudgment.status == "applied")
            .limit(1)
        )
        chains.append(
            {
                "article_id": event["article_id"],
                "cache_before": event["vector_cache_before"],
                "physical_requests": len(bills),
                "embedding_requests": sum(b.stage == "topic_embedding" for b in bills),
                "known_usd": str(known),
                "unresolved_reserved_usd": str(
                    sum(
                        (
                            b.reserved_usd
                            for b in bills
                            if b.status in {"reserved", "usage_unknown"}
                        ),
                        Decimal(0),
                    )
                ),
                "complete_successful_natural_chain": bool(query_tasks)
                and applied is not None
                and all(t.status == "completed" for t in query_tasks)
                and all(b.status == "responded" for b in bills),
            }
        )
    spec = entry.specs["exposed"]
    excluded = {q["article_id"] for q in spec["unavailable_inputs"]}
    expected = [q["article_id"] for q in spec["queries"] if q["article_id"] not in excluded]
    complete_run = (
        bool(events)
        and events[-1].get("event") == "complete"
        and (
            events[-1].get("completed_queries") == expected
            and events[-1].get("task_ids") == [t.id for t in tasks]
            and not any(t.status in UNFINISHED for t in tasks)
        )
    )
    result.update(
        execution_fingerprint=fingerprint(entry.execution),
        first_output_sha256=sha(first) if first.exists() else None,
        query_chain_receipts=chains,
        complete_exposed_run=complete_run,
        challenges=challenge_report(session, entry),
        cumulative_batch=batch_state(session),
        continuation_paid_stop=read_json(entry.stop) if entry.stop.exists() else None,
        new_blind_prepared_or_read=False,
        exposed_numeric_and_strict_basis_pass=complete_run
        and result["strict_basis_review_complete"]
        and result["unreviewed_applied"] == 0
        and result["invalid_reviewed_applied"]["numerator"] == 0
        and all(
            result[k]["value"] is not None and result[k]["value"] >= threshold
            for k, threshold in (
                ("candidate_recall", 0.90),
                ("judgment_precision", 0.95),
                ("strict_supported_final_coverage", 0.80),
            )
        ),
    )
    result["complete_successful_chain_costs"] = {
        state: [
            c["known_usd"]
            for c in chains
            if c["complete_successful_natural_chain"]
            and result["strict_basis_review_complete"]
            and result["invalid_reviewed_applied"]["numerator"] == 0
            and (
                "cold"
                if not c["cache_before"]["warm_keys"]
                else "warm"
                if len(c["cache_before"]["warm_keys"]) == c["cache_before"]["unique_inputs"]
                else "mixed"
            )
            == state
        ]
        or None
        for state in ("cold", "warm", "mixed")
    }
    return result


def reported_tasks(session: Session, entry: Entry) -> list[PipelineTask]:
    """Use the registered contract for reports without loading credential settings."""
    ids = sorted(t["id"] for t in entry.specs["exposed"]["topics"])
    return [
        task
        for task in session.scalars(
            select(PipelineTask)
            .where(PipelineTask.strategy_version == entry.execution["contract"]["version"])
            .order_by(PipelineTask.id)
        )
        if (task.kind == "topic_recall" and task.payload.get("trace", {}).get("topic_scope") == ids)
        or task.payload.get("candidate", {}).get("topic", {}).get("id") in ids
    ]


def report_entry(entry: Entry, findings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Reporting never needs paid authority, a key, provider access or mutable settings."""
    observed = False
    for phase in ("exposed", "challenge"):
        path = entry.first_output(phase)
        if path.exists():
            events = [json.loads(line) for line in path.read_text().splitlines()]
            if not events or not (
                events[0].get("event") == "start"
                and events[0].get("execution_fingerprint") == fingerprint(entry.execution)
                and events[0].get("registration") == entry.specs[phase]["id"]
            ):
                raise ValueError("retained first output has no matching registration provenance")
            observed = True
    if not observed:
        raise ValueError("no retained run exists; use offline prepare for unmeasured status")
    url = make_url(os.environ.get("UNSPUN_DATABASE_URL", ""))
    if url.host not in ("localhost", "127.0.0.1") or url.database != DATABASE:
        raise ValueError("read-only report requires the explicit original local ledger URL")
    engine = create_engine(url)
    try:
        with Session(engine) as session:
            session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
            return run_report(session, entry, findings)
    finally:
        engine.dispose()


def require_original_engine() -> Engine:
    url = make_url(get_settings().database_url)
    if url.host not in ("localhost", "127.0.0.1") or url.database != DATABASE:
        raise ValueError("continuation requires the original local cumulative evaluation ledger")
    return get_engine()


def paid_entry(
    entry: Entry, phase: str, review: Path | None, authorization: Path | None, proxy: str | None
) -> None:
    receipt = require_authority(entry, review, authorization, phase)
    provider_attempt = entry.evidence / f"{phase}-provider-read-attempt.json"
    if entry.stop.exists() or entry.first_output(phase).exists() or provider_attempt.exists():
        raise ValueError("a first output or continuation stop exists; no overwrite or resume")
    settings = get_settings()
    if member_contract() != entry.execution["contract"] or settings.grounding_budget_24h_usd != 1.0:
        raise ValueError("runtime contract or isolated grounding ceiling differs from review")
    if settings.openrouter_base_url != entry.execution["provider_reads"]["base_url"]:
        raise ValueError("provider endpoint differs from the reviewed read scope")
    engine = require_original_engine()
    with engine.connect() as lock:
        if not lock.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": RUN_LOCK}):
            raise ValueError("another member evaluation owns the original ledger")
        try:
            with Session(engine) as session:
                session.execute(text("SET TRANSACTION READ ONLY"))
                require_ledger(session, entry, receipt)
                require_exact_inputs(session, entry.specs[phase])
                if scoped_tasks(session, entry.specs[phase]):
                    raise ValueError("registered namespace already contains tasks")
                if phase == "challenge":
                    first = entry.first_output("exposed")
                    if (
                        not first.exists()
                        or json.loads(first.read_text().splitlines()[-1]).get("event") != "complete"
                    ):
                        raise ValueError("exposed must complete before the final challenge phase")
                policy = session.get(BudgetPolicy, 1)
                assert policy
                if (
                    policy.key_fingerprint
                    != hashlib.sha256(settings.openrouter_api_key.encode()).hexdigest()
                ):
                    raise ValueError("credential differs from the original cumulative ledger")
                state, budget = batch_state(session), budget_status(session)
                reason = stop_reason(session, entry, phase, Decimal("0.30"))
                if reason:
                    raise BudgetExceeded(reason)
            # No SSH credential loader, auto-allocation or fee settlement is available here.
            if not settings.openrouter_api_key:
                raise ValueError("original provider credential is required after authority checks")
            entry.evidence.mkdir(exist_ok=True)
            with provider_attempt.open("x") as output:
                json.dump(
                    {
                        "at": datetime.now(UTC).isoformat(),
                        "phase": phase,
                        "execution_fingerprint": fingerprint(entry.execution),
                        "method": "GET",
                        "path": "/key",
                        "attempt": 1,
                        "retries_allowed": 0,
                    },
                    output,
                    indent=2,
                    default=str,
                )
            with httpx.Client(
                base_url=settings.openrouter_base_url,
                headers={"Authorization": "Bearer " + settings.openrouter_api_key},
                proxy=proxy,
                timeout=30,
            ) as client:
                provider = provider_key_status(client)
            remaining = provider.get("limit_remaining")
            if remaining is None:
                raise BudgetExceeded("fresh provider remaining limit unavailable")
            known = Decimal(state["known_usd"])
            cap = min(
                Decimal("0.30"),
                known + Decimal("1.50") - Decimal(budget["accounting"]["occupancy_usd"]),
                known + Decimal(str(remaining)) - Decimal("0.484867"),
            )
            if cap <= known:
                raise BudgetExceeded("no remaining original pool after preserved holds")
            with (entry.evidence / f"{phase}-before-run.json").open("x") as output:
                json.dump(
                    {
                        "batch": state,
                        "budget": budget,
                        "provider": provider,
                        "effective_cumulative_pool_ceiling_usd": str(cap),
                    },
                    output,
                    indent=2,
                    default=str,
                )
            with Session(engine) as session, session.begin():
                require_ledger(session, entry, receipt)
                require_exact_inputs(session, entry.specs[phase])
                seed_topics(session, entry.specs[phase], load_sources())
            previous_enabled = settings.r2_member_processing_enabled
            settings.r2_member_processing_enabled = True
            try:
                (run_exposed if phase == "exposed" else run_challenges)(engine, entry, cap, proxy)
            except Exception as error:
                with Session(engine) as session:
                    mark_stop(
                        entry, phase, type(error).__name__ + ": " + str(error), batch_state(session)
                    )
                raise
            finally:
                settings.r2_member_processing_enabled = previous_enabled
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": RUN_LOCK})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "preflight", "run", "report"))
    parser.add_argument("--registration", type=Path, default=DEFAULT_REGISTRATION)
    parser.add_argument("--phase", choices=("exposed", "challenge"), default="exposed")
    parser.add_argument("--review", type=Path)
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--findings", type=Path)
    parser.add_argument("--proxy")
    args = parser.parse_args()
    entry = load_entry(args.registration)
    if args.action == "prepare":
        print(json.dumps(preparation(entry), indent=2))
        return
    if args.action == "preflight":
        require_authority(entry, args.review, args.authorization, args.phase)
        print(
            json.dumps(
                {
                    "offline_authority_validated": True,
                    "ledger_checked": False,
                    "paid_authority_is_not_ledger_reconciliation": True,
                }
            )
        )
        return
    if args.action == "report":
        result = report_entry(entry, read_json(args.findings) if args.findings else None)
        print(json.dumps(result, indent=2))
        return
    paid_entry(entry, args.phase, args.review, args.authorization, args.proxy)


if __name__ == "__main__":
    main()
