"""Isolation, retained accounting and blind-stage fencing; all HTTP is mocked."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from tests.test_member_processing import MemberDB, decision_for_prompt
from tests.test_member_quality import spec
from unspun.core.billing import BudgetExceeded
from unspun.core.member_recall import recall_plan
from unspun.evaluation import member_retest as retest
from unspun.pipeline.member_processing import MemberHandler
from unspun.pipeline.r1_worker import Blocked

pytest_plugins = ["tests.test_member_processing"]


def test_registered_pool_filters_topics_without_injecting_a_candidate(member_db: MemberDB) -> None:
    db = member_db
    with db.scope() as session:
        empty = recall_plan(
            session, db.article, db.sources, datetime.now(UTC), topic_ids=frozenset()
        )
        assert empty["topics"] == [] and empty["trace"]["topic_scope"] == []
        scoped = recall_plan(
            session, db.article, db.sources, datetime.now(UTC), topic_ids=frozenset({str(db.topic)})
        )
        assert [t["id"] for t in scoped["topics"]] == [str(db.topic)]
    db.enqueue()
    lease = db.claim("topic_recall")
    handler = MemberHandler({s.id: s for s in db.sources}, scope=db.scope, topic_ids=frozenset())
    with pytest.raises(Blocked, match="recall candidates changed"):
        handler.run(lease)
    assert not db.calls


def test_blind_payload_cannot_be_opened_before_complete_regression(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(retest, "EVIDENCE", tmp_path)
    value = {"blind_seal": "this-file-must-not-be-read"}
    with pytest.raises(ValueError, match="regression must complete"):
        retest.phase_spec(value, "blind")
    (tmp_path / "regression-first-run.ndjson").write_text('{"event":"halt"}\n')
    with pytest.raises(ValueError, match="regression must complete"):
        retest.phase_spec(value, "blind")


def test_refresh_deducts_future_reserve_before_provider_or_pool_cap(
    member_db: MemberDB, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = member_db
    value: dict[str, Any] = {
        "original_holds": [],
        "budget": {"future_reserved_usd": "0.03"},
        "phases": {"regression": {"cumulative_pool_ceiling_usd": "0.19"}},
    }

    def provider(_: Any) -> dict[str, str]:
        return {"limit_remaining": "0.04"}

    monkeypatch.setattr(retest, "provider_key_status", provider)
    reading = retest.refresh(db.billing.engine, value, "regression", None)
    assert Decimal(reading["effective_cumulative_pool_ceiling_usd"]) == Decimal("0.01")

    def ample_provider(_: Any) -> dict[str, str]:
        return {"limit_remaining": "15"}

    monkeypatch.setattr(retest, "provider_key_status", ample_provider)
    reading = retest.refresh(db.billing.engine, value, "regression", None)
    assert Decimal(reading["effective_cumulative_pool_ceiling_usd"]) == Decimal("0.17")
    assert not db.calls and not db.billing.requests()


def test_phase_guard_stops_before_a_second_physical_call(member_db: MemberDB) -> None:
    import httpx

    from unspun.core.llm import LlmClient

    db = member_db
    db.enqueue()
    lease = db.claim("topic_recall")
    value = spec(db)
    value["id"] = lease.worker
    journal = retest.RetestJournal(db.billing.engine, value, Decimal("0.20"), 1)
    handler = MemberHandler(
        {s.id: s for s in db.sources},
        scope=db.scope,
        client_factory=lambda context: LlmClient(
            context=context,
            transport=httpx.MockTransport(db.transport),
            journal_factory=lambda _: journal,
        ),
    )
    with pytest.raises(BudgetExceeded, match="phase physical request cap"):
        handler.run(lease)
    assert len(db.calls) == len(db.billing.requests()) == 1


def test_old_registration_stays_frozen_and_becomes_exposed_only_in_new_version() -> None:
    old = retest.registration(require_current_contract=False)
    value = retest.phase_spec(
        {
            "id": "synthetic-v3",
            "contract": {},
            "budget": {},
            "regression": {"seed_references": {t["key"]: {} for t in old["topics"]}},
        },
        "regression",
    )
    assert len(value["queries"]) == 12
    assert {q["split"] for q in value["queries"]} == {"exposed_regression"}
    assert sum(q["original_split"] == "holdout" for q in value["queries"]) == 5
    assert all(t["id"] != t["original_id"] for t in value["topics"])
    original = retest.registration(require_current_contract=False)
    assert sum(q["split"] == "holdout" for q in original["queries"]) == 5


def test_natural_phase_runs_real_queue_handler_and_cas(
    member_db: MemberDB, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import httpx

    from unspun.core.llm import LlmClient

    db = member_db
    value = spec(db)
    value["id"] = "synthetic-natural-retest"
    value["topics"] = [{"id": str(db.topic)}]
    execution = {"phases": {"regression": {"physical_request_limit": 10}}}
    original = LlmClient

    def client(**kwargs: Any) -> LlmClient:
        kwargs["transport"] = httpx.MockTransport(db.transport)
        return original(**kwargs)

    monkeypatch.setattr(retest, "load_sources", lambda: db.sources)
    monkeypatch.setattr(retest, "LlmClient", client)
    monkeypatch.setattr(retest, "EVIDENCE", tmp_path)
    retest.run_phase(db.billing.engine, execution, value, "regression", Decimal("0.20"), None)
    assert db.judgment().status == "applied"
    assert len(db.calls) == 7
    assert '"event": "complete"' in (tmp_path / "regression-first-run.ndjson").read_text()
    retest.require_phase_complete(db.billing.engine, execution, "regression", value)
    with db.scope() as session:
        assert len(retest.phase_tasks(session, value["id"])) == 3


def test_phase_cap_retains_calls_after_task_completion(
    member_db: MemberDB, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import httpx

    from unspun.core.llm import LlmClient

    db = member_db
    value = spec(db)
    value.update(id="synthetic-two-tasks", topics=[{"id": str(db.topic)}])
    execution = {"phases": {"regression": {"physical_request_limit": 2}}}
    original = LlmClient

    def client(**kwargs: Any) -> LlmClient:
        kwargs["transport"] = httpx.MockTransport(db.transport)
        return original(**kwargs)

    monkeypatch.setattr(retest, "load_sources", lambda: db.sources)
    monkeypatch.setattr(retest, "LlmClient", client)
    monkeypatch.setattr(retest, "EVIDENCE", tmp_path)
    retest.run_phase(db.billing.engine, execution, value, "regression", Decimal("0.20"), None)
    assert len(db.calls) == len(db.billing.requests()) == 2
    assert '"event": "halt"' in (tmp_path / "regression-first-run.ndjson").read_text()
    with pytest.raises(ValueError, match="exact frozen"):
        retest.require_phase_complete(db.billing.engine, execution, "regression", value)


@pytest.mark.parametrize("limit", [1, 6])
def test_challenge_uses_real_reviewer_and_rejects_registered_revision_race(
    member_db: MemberDB, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, limit: int
) -> None:
    import httpx

    from unspun.core.llm import LlmClient
    from unspun.evaluation import member_retest_challenge as challenge

    db = member_db
    db.enqueue()
    _, recalled = db.step("topic_recall")
    topic = recalled["candidates"][0]["topic"]
    with db.scope() as session:
        query = retest.current_input(session, db.article, db.sources, datetime.now(UTC))
    value = spec(db)
    value.update(
        id="synthetic-challenge",
        cases=[
            {
                "id": "revision-race",
                "topic_id": str(db.topic),
                "article_id": db.article,
                "force_revision_after_review": True,
                "decision": decision_for_prompt(
                    __import__(
                        "unspun.pipeline.member_processing", fromlist=["_prompt_packet"]
                    )._prompt_packet({"query": query, "candidate": {"topic": topic}}, None)
                ),
            }
        ],
    )
    execution = {
        "challenges": value,
        "budget": value["budget"],
        "phases": {"challenge": {"physical_request_limit": limit}},
    }
    original = LlmClient

    def client(**kwargs: Any) -> LlmClient:
        kwargs["transport"] = httpx.MockTransport(db.transport)
        return original(**kwargs)

    monkeypatch.setattr(challenge, "load_sources", lambda: db.sources)
    monkeypatch.setattr(challenge, "LlmClient", client)
    monkeypatch.setattr(challenge, "EVIDENCE", tmp_path)
    challenge.run_challenges(db.billing.engine, execution, Decimal("0.20"), None)
    row = db.judgment()
    assert '"natural_end_to_end": false' in (tmp_path / "challenge-first-run.ndjson").read_text()
    if limit == 1:
        assert row.status == "draft" and row.review is None
        assert len(db.calls) == 3
        assert '"event": "halt"' in (tmp_path / "challenge-first-run.ndjson").read_text()
    else:
        assert row.status == "stale" and row.review and len(row.review["audits"]) == 4
        assert len(db.calls) == 6
