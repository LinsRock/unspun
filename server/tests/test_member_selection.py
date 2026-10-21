"""Exact selections over exposed originals and fault propagation, with zero live HTTP.

Registered semantic rejections are injected responses. They demonstrate that valid
string positions still require semantic audits, not that a model detects the fault.
"""

import gzip
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.test_billing import BillingDB
from tests.test_member_grounding import judged
from tests.test_member_processing import MemberDB
from unspun.core.billing import CallContext
from unspun.core.config import get_settings
from unspun.core.content import fingerprint
from unspun.core.llm import LlmClient
from unspun.core.member_contracts import (
    AUDIT_KINDS,
    AUDIT_PROMPTS,
    MEMBER_OUTPUT_BYTES,
    AuditKind,
    MemberAuditContent,
    MemberDecision,
    member_contract,
    project_classification,
)
from unspun.core.member_evidence import (
    audit_packet,
    audit_supported,
    audit_targets,
    review_binding,
    validate_selection,
)
from unspun.core.member_receipts import audit_from_call
from unspun.core.models import Article
from unspun.core.task_models import PipelineTask
from unspun.core.tasks import claim, enqueue
from unspun.core.topic_models import TopicMember
from unspun.pipeline.member_processing import MemberHandler
from unspun.pipeline.r1_worker import Handlers, process_one

pytest_plugins = ["tests.test_member_processing"]
ROOT = Path(__file__).resolve().parents[2]
SPEC = json.loads((ROOT / "docs/acceptance/r2-06-selection/challenges.json").read_text())
SOURCE = ROOT / SPEC["source"]
TASKS = {t["id"]: t for t in json.loads(gzip.decompress(SOURCE.read_bytes()))}
CASES: list[dict[str, Any]] = SPEC["cases"]


def packet_for(case: dict[str, Any]) -> dict[str, Any]:
    original = deepcopy(TASKS[case["task_id"]]["payload"])
    original["contract"] = member_contract()
    return original


def test_original_challenge_artifact_is_frozen_and_never_new_blind() -> None:
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == SPEC["source_sha256"]
    assert SPEC["semantic_credit"] is False and SPEC["new_blind"] is False
    assert SPEC["paid_calls"] == 0


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_registered_original_selection_boundary(case: dict[str, Any]) -> None:
    original = deepcopy(case["decision"])
    if case["expected_boundary"] == "schema":
        with pytest.raises(ValidationError):
            MemberDecision.model_validate(original)
        return
    decision = MemberDecision.model_validate(original)
    if case["expected_boundary"] == "mechanical":
        with pytest.raises(ValueError):
            validate_selection(packet_for(case), decision)
        return
    assert validate_selection(packet_for(case), decision)
    # Semantic faults deliberately PASS string/structure validation.
    assert decision.model_dump(mode="json") == original
    if case["id"] == "analysis-contribution-control":
        assert decision.identity == "same_occurrence" and decision.classification == "opinion"
    if case["id"] == "date-conflict-retained":
        assert decision.classification == "independent" and decision.relation.time == "conflicting"


SEMANTIC = [c for c in CASES if c["expected_boundary"] == "semantic"]


@pytest.mark.parametrize("case", SEMANTIC, ids=[c["id"] for c in SEMANTIC])
def test_literal_matches_still_need_receipted_semantic_support(
    billing_db: BillingDB, monkeypatch: pytest.MonkeyPatch, case: dict[str, Any]
) -> None:
    monkeypatch.setenv("UNSPUN_R2_MEMBER_PROCESSING_ENABLED", "true")
    get_settings.cache_clear()
    db = billing_db
    db.policy(stage_caps={"topic_review": "0.30"})
    packet = packet_for(case)
    decision = MemberDecision.model_validate(case["decision"])
    assert validate_selection(packet, decision)
    target = case["rejection_target"]
    kind = cast(
        AuditKind,
        "query_support"
        if target.startswith("query_")
        else "anchor_support"
        if target.startswith("anchor_")
        else "relation",
    )
    content = packet["query"]["content"]
    with Session(db.engine) as session, session.begin():
        session.add(
            Article(
                id=content["article_id"],
                source_id=content["source_id"],
                title=content["title"],
                url="https://offline.invalid/" + case["id"],
            )
        )
        session.flush()
        task = enqueue(
            session,
            queue="paid",
            kind="topic_review",
            object_key="content:" + str(content["article_id"]),
            article_id=content["article_id"],
            source_id=content["source_id"],
            input_fingerprint=fingerprint(packet),
            strategy_version=str(member_contract()["version"]),
            payload=packet,
            max_attempts=1,
        )
        lease = claim(session, queue="paid", kinds={"topic_review"}, worker="offline-selection")
        assert lease and lease.task_id == task
    calls: list[httpx.Request] = []

    def rejection(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        supplied = json.loads(json.loads(request.content)["messages"][1]["content"])
        if kind == "query_support":
            assert "candidate" not in supplied and "decision" not in supplied
            assert all(m["role"] == "query" for m in supplied["materials"])
        if kind == "anchor_support":
            assert all(m["role"] == "anchor" for m in supplied["materials"])
        # An explicit oracle, not a real semantic model or a measured success.
        raw = {
            "checks": [
                {
                    "target": t,
                    "status": "unsupported" if t == target else "supported",
                    "issues": [case["review_note"]] if t == target else [],
                }
                for t in supplied["targets"]
            ],
            "issues": [],
        }
        return httpx.Response(
            200,
            json={
                "id": "offline-selection-" + uuid4().hex,
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(raw)}}],
                "usage": {"cost": "0.00001", "prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    with (
        Session(db.engine) as session,
        LlmClient(
            context=CallContext(
                stage="topic_review",
                phase="review",
                logical_key=lease.kind + ":" + lease.input_fingerprint + ":" + kind,
                lease=lease,
            ),
            transport=httpx.MockTransport(rejection),
        ) as client,
    ):
        raw = client.chat_json(
            session,
            model=get_settings().viewpoint_model,
            system=AUDIT_PROMPTS[kind],
            user=json.dumps(audit_packet(packet, decision, kind), ensure_ascii=False),
            purpose="grounding",
            max_tokens=4096,
        )
        audit = audit_from_call(session, lease, decision, kind, client.call_ids[-1], raw)
    assert len(calls) == 1
    assert not audit_supported(
        audit, review_binding(packet, decision), audit_targets(decision, kind)
    )
    assert decision.model_dump(mode="json") == case["decision"]


@pytest.mark.parametrize("kind", AUDIT_KINDS)
def test_any_semantic_failure_stops_remaining_audits_and_cas(
    member_db: MemberDB, kind: AuditKind
) -> None:
    db = member_db
    judged(db)
    original = deepcopy(db.judgment().decision)
    lease = db.claim("topic_review")
    before = len(db.calls)

    def reject_selected(request: httpx.Request) -> httpx.Response:
        supplied = json.loads(json.loads(request.content)["messages"][1]["content"])
        db.approved = supplied["kind"] != kind
        return db.transport(request)

    handler = MemberHandler(
        {s.id: s for s in db.sources},
        scope=db.scope,
        client_factory=lambda context: LlmClient(
            context=context, transport=httpx.MockTransport(reject_selected)
        ),
    )
    assert db.finish(lease, handler.run(lease))
    assert len(db.calls) - before == AUDIT_KINDS.index(kind) + 1
    assert db.judgment().decision == original and db.judgment().status == "rejected"
    with db.scope() as session:
        assert session.get(TopicMember, (str(db.topic), db.article)) is None


@pytest.mark.parametrize("fault", ["truncated", "bytes", "schema"])
@pytest.mark.parametrize("stage", ["topic_judge", "topic_review"])
def test_member_output_failure_has_one_request_and_no_automatic_retry(
    member_db: MemberDB, fault: str, stage: str
) -> None:
    db = member_db
    db.enqueue()
    db.step("topic_recall")
    if stage == "topic_review":
        db.step("topic_judge")
    before = len(db.calls)

    def broken(request: httpx.Request) -> httpx.Response:
        response = db.transport(request).json()
        choice = response["choices"][0]
        if fault == "truncated":
            choice["finish_reason"] = "length"  # Even complete JSON must fail.
        elif fault == "bytes":
            choice["message"]["content"] += " " * MEMBER_OUTPUT_BYTES
        else:
            choice["message"]["content"] = '{"invalid": true}'
        return httpx.Response(200, json=response)

    handler = MemberHandler(
        {s.id: s for s in db.sources},
        scope=db.scope,
        client_factory=lambda context: LlmClient(
            context=context, transport=httpx.MockTransport(broken)
        ),
    )
    handlers: Handlers = {("paid", stage): handler}
    assert process_one("paid", handlers, worker="bounded", scope=db.scope)
    assert not process_one("paid", handlers, worker="bounded", scope=db.scope)
    assert len(db.calls) - before == 1
    assert db.billing.requests()[-1].response_payload  # First failure survives.
    with db.scope() as session:
        task = session.scalar(select(PipelineTask).where(PipelineTask.kind == stage))
        assert task and task.status == "failed" and task.max_attempts == 1
        assert session.get(TopicMember, (str(db.topic), db.article)) is None


@pytest.mark.parametrize("bytes_over", [0, 1])
def test_aggregate_quote_byte_limit_not_per_fact_sample_maximum(bytes_over: int) -> None:
    raw = deepcopy(CASES[0]["decision"])
    fact = raw["query_facts"][0]
    template = fact["citations"][0]
    quotes = ["x" * 8000, "x" * 8000, "x" * (384 + bytes_over)]
    first = deepcopy(fact)
    first["citations"] = [{**template, "quote": q, "start": 0, "end": len(q)} for q in quotes[:2]]
    second = deepcopy(fact)
    second["citations"] = [{**template, "quote": quotes[2], "start": 0, "end": len(quotes[2])}]
    raw.update(query_facts=[first], anchor_facts=[second])
    if bytes_over:
        with pytest.raises(ValidationError, match="aggregate byte bound"):
            MemberDecision.model_validate(raw)
    else:
        assert MemberDecision.model_validate(raw)


def test_audit_total_bytes_and_maximum_target_count() -> None:
    raw = {
        "checks": [
            {"target": str(i), "status": "unsupported", "issues": ["x" * 2000] * 10}
            for i in range(20)
        ],
        "issues": [],
    }
    with pytest.raises(ValidationError, match="byte bound"):
        MemberAuditContent.model_validate(raw)
    decision = MemberDecision.model_validate(CASES[0]["decision"])
    full = decision.model_copy(
        update={"query_facts": decision.query_facts * 4, "anchor_facts": decision.anchor_facts * 4}
    )
    assert len(audit_targets(full, "complete_basis")) == 16
    assert len(full.basis) <= 2000


@pytest.mark.parametrize(
    "field", ["subject", "action", "object", "location", "attribution", "time"]
)
def test_missing_roles_are_not_repaired(field: str) -> None:
    raw = deepcopy(CASES[0]["decision"])
    del raw["query_facts"][0][field]
    with pytest.raises(ValidationError):
        MemberDecision.model_validate(raw)


def test_projection_preserves_first_association_despite_bad_schema() -> None:
    assert (
        project_classification(
            {"identity": "same_occurrence", "contribution": "report", "certainty": "certain"}
        )
        == "same_event"
    )
    assert (
        project_classification(
            {"identity": "same_occurrence", "contribution": "opinion", "certainty": "certain"}
        )
        == "opinion"
    )
    assert (
        project_classification(
            {
                "identity": "same_occurrence",
                "contribution": ["opinion", "report"],
                "certainty": "certain",
            }
        )
        is None
    )
    assert (
        project_classification(
            {"identity": "same_occurrence", "contribution": "report", "certainty": "uncertain"}
        )
        == "independent"
    )


def test_old_paid_registrations_reject_new_contract_without_provider_calls() -> None:
    from unspun.evaluation import member_grounding, member_quality, member_retest

    for load in (
        member_quality.registration,
        member_grounding.load_execution,
        member_retest.load_execution,
    ):
        with pytest.raises(ValueError, match="contract|frozen"):
            load()
