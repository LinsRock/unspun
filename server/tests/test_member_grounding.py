"""Owned-reference and complete audit fences; all external calls are mocked."""

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from tests.test_member_processing import MemberDB
from tests.test_tasks import TaskDB
from unspun.core.member_contracts import MemberDecision
from unspun.core.member_evidence import expanded_evidence, reference_catalog
from unspun.core.member_recall import validate_decision
from unspun.core.task_models import PipelineTask, TaskAttempt
from unspun.core.tasks import claim
from unspun.core.topic_models import TopicMember

pytest_plugins = ["tests.test_member_processing", "tests.test_tasks"]


def judged(db: MemberDB) -> tuple[Any, dict[str, Any]]:
    db.enqueue()
    db.step("topic_recall")
    return db.step("topic_judge")


def test_query_support_packet_has_only_query_original(member_db: MemberDB) -> None:
    db = member_db
    judged(db)
    db.step("topic_review")
    packets = [
        json.loads(call["messages"][1]["content"]) for call in db.calls if "messages" in call
    ]
    audits = packets[1:]
    assert [p["kind"] for p in audits] == [
        "query_support",
        "anchor_support",
        "relation",
        "complete_basis",
    ]
    own, anchor = audits[:2]
    assert "candidate" not in own and "decision" not in own and "complete_basis" not in own
    assert len(own["materials"]) == 1
    assert own["materials"][0]["content"]["article_id"] == db.article
    assert own["materials"][0]["role"] == "query"
    assert all(m["content"]["article_id"] == db.anchor for m in anchor["materials"])
    assert "query" not in anchor and "decision" not in anchor
    assert all(p["binding"] == audits[0]["binding"] for p in audits)
    assert all("audits" not in p for p in audits)  # Earlier approval never primes another auditor.


@pytest.mark.parametrize(
    "scope,voice",
    [
        ("media_description", "description"),
        ("question_background", "question"),
    ],
)
def test_reference_catalog_binds_paragraph_owner_and_scope_voice(
    member_db: MemberDB, scope: str, voice: str
) -> None:
    db = member_db
    lease, _ = judged(db)
    packet = deepcopy(lease.payload)
    packet["query"]["content"]["scope"] = scope
    catalog = reference_catalog(packet)
    owned = [row for row in catalog.values() if row["role"] == "query"]
    assert owned and {r["voice"] for r in owned} == {voice}
    assert {r["article_id"] for r in owned} == {db.article}
    assert {r["paragraph"] for r in owned} == {0}
    assert not set(catalog).intersection(
        key for key, row in reference_catalog(lease.payload).items() if row["role"] == "query"
    )


def test_new_reference_expansion_never_repairs_legacy_fields(member_db: MemberDB) -> None:
    db = member_db
    lease, out = judged(db)
    original = deepcopy(out["decision"])
    decision = MemberDecision.model_validate(original)
    refs = expanded_evidence(lease.payload, decision)
    assert [(r.article_id, r.paragraph, r.voice) for r in refs] == [
        (db.article, 0, "reported"),
        (db.anchor, 0, "reported"),
    ]
    legacy = {
        "classification": "same_event",
        "certainty": "certain",
        "basis": "Legacy basis",
        "evidence": [
            {
                "article_id": db.article,
                "material_id": refs[0].material_id,
                "paragraph": 0,
                "quote": refs[0].quote,
            }
        ],
    }
    with pytest.raises(ValidationError):
        MemberDecision.model_validate(legacy)
    assert out["decision"] == original


@pytest.mark.parametrize(
    "field",
    [
        "decision_fingerprint",
        "materials_fingerprint",
        "contract_fingerprint",
        "references_fingerprint",
        "packet_fingerprint",
    ],
)
def test_every_audit_binding_is_required_before_cas(member_db: MemberDB, field: str) -> None:
    db = member_db
    judged(db)
    lease = db.claim("topic_review")
    result = db.handler().run(lease)
    original = deepcopy(db.judgment().decision)
    result["review"]["audits"][-1]["binding"][field] = "0" * 64
    assert db.finish(lease, result)
    assert db.judgment().status == "rejected"
    assert db.judgment().decision == original
    with db.scope() as session:
        assert session.get(TopicMember, (str(db.topic), db.article)) is None


@pytest.mark.parametrize(
    "change", ["missing", "duplicate", "unsupported", "uncertain", "issues", "partial"]
)
def test_full_basis_coverage_must_be_complete_and_supported(
    member_db: MemberDB, change: str
) -> None:
    db = member_db
    judged(db)
    lease = db.claim("topic_review")
    result = db.handler().run(lease)
    basis = result["review"]["audits"][-1]
    if change == "missing":
        basis["checks"].pop()
    elif change == "duplicate":
        basis["checks"][-1] = basis["checks"][0]
    elif change in ("unsupported", "uncertain"):
        basis["checks"][0]["status"] = change
    elif change == "issues":
        basis["checks"][0]["issues"] = ["An anchor-only fact was attributed to the query"]
    else:
        result["review"]["audits"].pop()
    original = deepcopy(db.judgment().decision)
    assert db.finish(lease, result)
    assert db.judgment().status == "rejected" and db.judgment().decision == original


@pytest.mark.parametrize("field", ["approved", "revised_decision"])
def test_approval_or_rewritten_basis_cannot_replace_audit_checks(
    member_db: MemberDB, field: str
) -> None:
    db = member_db
    judged(db)
    lease = db.claim("topic_review")
    result = db.handler().run(lease)
    result["review"]["audits"][-1][field] = True if field == "approved" else {}
    with pytest.raises(ValidationError):
        db.finish(lease, result)
    assert db.judgment().status == "draft"


def test_rejected_query_claim_stops_without_deleting_it(member_db: MemberDB) -> None:
    db = member_db
    judged(db)
    original = deepcopy(db.judgment().decision)
    db.approved = False
    db.step("topic_review")
    row = db.judgment()
    assert row.status == "rejected" and row.decision == original
    assert row.review and len(row.review["audits"]) == 1
    assert len(db.calls) == 4  # Two vectors, judgment, query-only support; no other audit.


def test_unknown_reference_is_failure_even_for_independent(member_db: MemberDB) -> None:
    db = member_db
    lease, out = judged(db)
    raw = deepcopy(out["decision"])
    raw["classification"] = "independent"
    raw["query_facts"][0]["citations"][0]["reference_id"] = "ref_" + "0" * 24
    decision = MemberDecision.model_validate(raw)
    with db.scope() as session, pytest.raises(ValueError, match="unknown or stale"):
        validate_decision(session, lease.payload, decision)


def test_task_namespace_filter_preserves_old_expired_task_and_attempt(task_db: TaskDB) -> None:
    old, new = task_db.add("old"), task_db.add("new")
    with task_db.scope() as session:
        previous = claim(
            session, queue="discovery", kinds={"probe"}, worker="old", task_ids=frozenset({old})
        )
        assert previous
        row = session.get(PipelineTask, old)
        assert row
        row.lease_until = datetime.now(UTC) - timedelta(seconds=1)
    with task_db.scope() as session:
        selected = claim(
            session, queue="discovery", kinds={"probe"}, worker="new", task_ids=frozenset({new})
        )
        assert selected and selected.task_id == new
        row = session.get(PipelineTask, old)
        attempt = session.get(TaskAttempt, previous.attempt_id)
        assert row and row.status == "running" and row.failures == 0
        assert attempt and attempt.status == "running"
