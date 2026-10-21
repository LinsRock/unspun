"""Cumulative revision, namespace retention and fresh-blind gates; no external HTTP."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.test_member_processing import MemberDB
from tests.test_member_quality import spec
from unspun.core.billing import BudgetExceeded, CallContext
from unspun.core.billing_models import BudgetPolicy
from unspun.core.content import fingerprint
from unspun.core.llm import LlmClient
from unspun.core.task_models import PipelineTask
from unspun.core.tasks import enqueue
from unspun.evaluation import member_grounding as grounding

pytest_plugins = ["tests.test_member_processing"]


def execution(db: MemberDB) -> tuple[dict[str, Any], dict[str, Any]]:
    value = spec(db)
    value.update(id="synthetic-grounding:exposed", topics=[{"id": str(db.topic)}])
    exe = {
        "id": "synthetic-grounding",
        "budget": value["budget"],
        "phases": {"exposed": {"physical_request_limit": 12}},
    }
    return exe, value


def test_new_namespace_does_not_claim_or_modify_old_budget_deferred_task(
    member_db: MemberDB, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db = member_db
    exe, value = execution(db)
    with db.scope() as session:
        old = enqueue(
            session,
            queue="paid",
            kind="topic_review",
            object_key="old-run:content",
            article_id=db.article,
            source_id=db.sources[0].id,
            input_fingerprint=fingerprint("retained-old"),
            strategy_version="r2-member-v3",
            payload={"preserve": "the old task110-style historical state"},
        )
        row = session.get(PipelineTask, old)
        assert row
        row.status = "budget_deferred"
    original = LlmClient

    def client(**kwargs: Any) -> LlmClient:
        kwargs["transport"] = httpx.MockTransport(db.transport)
        return original(**kwargs)

    monkeypatch.setattr(grounding, "load_sources", lambda: db.sources)
    monkeypatch.setattr(grounding, "LlmClient", client)
    monkeypatch.setattr(grounding, "EVIDENCE", tmp_path)
    frozen = tmp_path / "source.json"
    frozen.write_text("frozen")
    monkeypatch.setattr(grounding, "FREEZE", frozen)
    grounding.run_exposed(db.billing.engine, exe, value, Decimal("0.30"), None)
    assert db.judgment().status == "applied" and len(db.calls) == 7
    with db.scope() as session:
        row = session.get(PipelineTask, old)
        assert row and row.status == "budget_deferred" and row.attempts == 0
        assert row.payload == {"preserve": "the old task110-style historical state"}
    assert '"event": "complete"' in (tmp_path / "exposed-first-run.ndjson").read_text()


def test_authorized_revision_keeps_total_and_all_history(
    member_db: MemberDB, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = member_db
    with db.scope() as session:
        policy = session.get(BudgetPolicy, 1)
        assert policy
        previous = dict(policy.stage_caps)
    exe = {
        "budget": {
            "previous_physical_requests": 0,
            "previous_spend_usd": "0",
            "previous_stage_caps_usd": previous,
            "stage_caps_usd": {
                "topic_embedding": "0.02",
                "topic_judgment": "0.13",
                "topic_review": "0.30",
            },
        }
    }

    def reviewed(_: dict[str, Any]) -> None:
        return None

    monkeypatch.setattr(grounding, "require_reviewed_entry", reviewed)
    receipt = grounding.allocate(db.billing.engine, exe)
    assert receipt["before"]["monthly_limit_usd"] == receipt["after"]["monthly_limit_usd"]
    assert (
        receipt["after"]["scope"] == "evaluation" and receipt["fees_or_reservations_reset"] is False
    )
    assert not db.billing.requests() and not db.calls
    with pytest.raises(ValueError, match="registered original policy"):
        grounding.allocate(db.billing.engine, exe)


def test_new_batch_stop_marker_fences_all_subsequent_phases(
    member_db: MemberDB, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db = member_db
    exe, value = execution(db)
    monkeypatch.setattr(grounding, "EVIDENCE", tmp_path)
    grounding.mark_stop("challenge", "physical cap reached", {})
    first = (tmp_path / "paid-stop.json").read_bytes()
    grounding.mark_stop("exposed", "must not replace first stop", {})
    assert (tmp_path / "paid-stop.json").read_bytes() == first
    db.enqueue()
    lease = db.claim("topic_recall")
    value["id"] = lease.worker
    journal = grounding.GroundingJournal(db.billing.engine, value, exe, "exposed", Decimal("0.30"))
    with db.scope() as session, pytest.raises(BudgetExceeded, match="already stopped"):
        journal.extra_physical_guard(
            session,
            CallContext(lease=lease),
        )
    assert not db.calls and not db.billing.requests()


def test_failed_exposed_gate_does_not_open_any_fresh_blind_path(
    member_db: MemberDB, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(grounding, "EVIDENCE", tmp_path)
    exe = {"new_blind_seal": "/must-never-be-opened"}
    with pytest.raises(ValueError, match="exposed gates must pass"):
        grounding.blind_spec(member_db.billing.engine, exe)
    (tmp_path / "exposed-gate.json").write_text(
        json.dumps({"exposed_numeric_and_strict_basis_pass": False})
    )
    with pytest.raises(ValueError, match="exposed gates must pass"):
        grounding.blind_spec(member_db.billing.engine, exe)


def test_exposed_registration_includes_all_previous_blind_queries_and_original_denominators() -> (
    None
):
    root = grounding.ROOT / "docs/evaluations/r2"
    value = json.loads((root / "member-grounding-exposed-v1.json").read_text())
    assert len(value["queries"]) == 18 and len(value["topics"]) == 16
    assert sum(len(q["expected_associations"]) for q in value["queries"]) == 9
    previous = [q for q in value["queries"] if q["exposure_origin"] == "previously_blind"]
    assert {q["article_id"] for q in previous} == {9192, 9051, 9125, 9182, 9098, 8981}
    assert all(q["original_split"] == "holdout" for q in previous)
    assert all(q["split"] == "exposed_validation" for q in value["queries"])
    assert [q["article_id"] for q in value["unavailable_inputs"]] == [8877]
    assert all(t["id"] != t["original_id"] and t["seed_reference"] for t in value["topics"])


def test_challenge_replays_actual_audit_and_races_two_complete_reviews(
    member_db: MemberDB, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from uuid import uuid4

    from tests.test_content_feed import ready
    from tests.test_member_processing import decision_for_prompt
    from tests.test_topics import DEFINITION, member, write
    from unspun.core.member_contracts import member_contract, project_material
    from unspun.core.member_recall import current_input, topic_candidate
    from unspun.core.models import Article
    from unspun.evaluation import member_grounding_challenge as challenge
    from unspun.pipeline.member_processing import enqueue_member_processing

    db = member_db
    db.enqueue()
    db.step("topic_recall")
    with db.scope() as session:
        other = ready(session)
        other_id = other.id
        replay, race = uuid4(), uuid4()
        for identity in (replay, race):
            write(session, identity, DEFINITION, db.sources)
            anchor = session.get(Article, db.anchor)
            assert anchor
            write(session, identity, member(anchor), db.sources)
        enqueue_member_processing(session, other_id, sources=db.sources, now=datetime.now(UTC))
    db.step("topic_recall")
    cases: list[dict[str, Any]] = []
    with db.scope() as session:
        for name, article, topic in [
            ("correct-complete", db.article, db.topic),
            ("stale-audit-replay", db.article, replay),
            ("cas-race-a", db.article, race),
            ("cas-race-b", other_id, race),
        ]:
            packet: dict[str, Any] = {
                "query": current_input(session, article, db.sources, datetime.now(UTC)),
                "candidate": {
                    "topic": topic_candidate(session, str(topic), db.sources, datetime.now(UTC))
                },
                "contract": member_contract(),
            }
            case = {
                "id": name,
                "article_id": article,
                "topic_id": str(topic),
                "decision": decision_for_prompt(
                    {
                        "query": project_material(packet["query"], "query"),
                        "candidate": {
                            "topic": {
                                "anchors": [
                                    {
                                        "snapshot": project_material(
                                            packet["candidate"]["topic"]["anchors"][0]["snapshot"],
                                            "anchor",
                                        )
                                    }
                                ]
                            }
                        },
                    }
                ),
            }
            if name == "stale-audit-replay":
                case["replay_actual_review_from"] = "correct-complete"
            if name.startswith("cas-race"):
                case["cas_competition_group"] = "two-real-reviews"
            cases.append(case)
    value = spec(db)
    value.update(
        id="synthetic-grounding:challenge",
        topics=[{"id": str(t)} for t in (db.topic, replay, race)],
        queries=[{"article_id": i} for i in (db.article, other_id)],
        cases=cases,
    )
    value["budget"]["stage_physical_limits"] = {
        "topic_embedding": 10,
        "topic_judgment": 12,
        "topic_review": 32,
    }
    value["budget"]["physical_request_limit"] = 80
    exe = {
        "id": "synthetic-grounding",
        "budget": value["budget"],
        "phases": {"challenge": {"physical_request_limit": 36}},
    }
    original = LlmClient

    def client(**kwargs: Any) -> LlmClient:
        kwargs["transport"] = httpx.MockTransport(db.transport)
        return original(**kwargs)

    monkeypatch.setattr(grounding, "load_sources", lambda: db.sources)
    monkeypatch.setattr(grounding, "LlmClient", client)
    monkeypatch.setattr(grounding, "EVIDENCE", tmp_path)
    monkeypatch.setattr(challenge, "EVIDENCE", tmp_path)
    frozen = tmp_path / "frozen.json"
    frozen.write_text("frozen")
    monkeypatch.setattr(challenge, "FREEZE", frozen)
    challenge.run_challenges(db.billing.engine, exe, value, Decimal("0.30"), None)
    records = [
        json.loads(line)
        for line in (tmp_path / "challenge-first-run.ndjson").read_text().splitlines()
    ]
    assert records[-1]["event"] == "complete"
    replayed = next(
        r
        for r in records
        if r.get("case_id") == "stale-audit-replay" and r["event"] == "actual_review_result"
    )
    assert replayed["status"] == "rejected" and replayed["replayed_from_review_task"]
    raced = next(r for r in records if r["event"] == "actual_cas_competition")
    assert sorted(raced["statuses"]) == ["applied", "stale"]
    assert raced["accepted_task_completions"] == [True, True]
    assert all(r.get("natural_end_to_end", False) is False for r in records)
