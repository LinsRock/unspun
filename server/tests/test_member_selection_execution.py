"""Offline entry authorization and isolated v6 execution; all provider HTTP is mocked."""

import copy
import gzip
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import Engine, select

from tests.test_content_feed import ready
from tests.test_member_processing import MemberDB, decision_for_prompt
from tests.test_member_quality import spec
from tests.test_topics import DEFINITION, member, write
from unspun.core.billing import BudgetExceeded
from unspun.core.billing_models import BilledRequest, BudgetPolicy
from unspun.core.content import fingerprint
from unspun.core.llm import LlmClient
from unspun.core.member_contracts import MemberDecision, member_contract, project_material
from unspun.core.member_evidence import validate_selection
from unspun.core.member_models import MemberJudgment
from unspun.core.member_recall import current_input, topic_candidate
from unspun.core.models import Article
from unspun.core.task_models import PipelineTask
from unspun.core.tasks import enqueue
from unspun.evaluation import member_selection_execution as execution
from unspun.pipeline.member_processing import enqueue_member_processing

pytest_plugins = ["tests.test_member_processing"]


def synthetic_entry(db: MemberDB, tmp_path: Path) -> execution.Entry:
    value = spec(db)
    value.update(
        id="synthetic-selection:exposed",
        topics=[{"id": str(db.topic), "key": "event"}],
        unavailable_inputs=[],
        queries=[{"article_id": db.article, "expected_associations": {"event": ["same_event"]}}],
    )
    value["budget"]["stage_physical_limits"] = {
        "topic_embedding": 80,
        "topic_judgment": 184,
        "topic_review": 96,
    }
    value["budget"]["physical_request_limit"] = 360
    return execution.Entry(
        tmp_path,
        tmp_path / "registration.json",
        {
            "id": "synthetic-selection",
            "evidence_directory": ".",
            "contract": member_contract(),
            "budget": value["budget"],
            "phases": {
                "exposed": {
                    "physical_request_limit": 124,
                    "previous_physical_requests": 0,
                }
            },
        },
        {"exposed": value},
    )


def mock_runner(db: MemberDB, monkeypatch: pytest.MonkeyPatch) -> None:
    original = LlmClient

    def client(**kwargs: Any) -> LlmClient:
        kwargs["transport"] = httpx.MockTransport(db.transport)
        return original(**kwargs)

    monkeypatch.setattr(execution, "load_sources", lambda: db.sources)
    monkeypatch.setattr(execution, "LlmClient", client)


def test_preparation_never_reads_settings_database_credentials_or_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("offline preparation must not access settings, DB or provider")

    monkeypatch.setattr(execution, "get_settings", forbidden)
    monkeypatch.setattr(execution, "get_engine", forbidden)
    monkeypatch.setattr(execution, "provider_key_status", forbidden)
    entry = execution.load_entry()
    result = execution.preparation(entry)
    assert (
        result["registered_queries"],
        result["executable_queries"],
        result["expected_pairs"],
    ) == (18, 17, 9)
    assert result["challenge_maximum_new_physical_audits"] == 23
    assert result["remaining_phase_requests"] == {"challenge": 23, "exposed": 105}
    assert not result["database_access"] and not result["semantic_credit"]
    for phase in ("exposed", "challenge"):
        with pytest.raises(ValueError, match="authorization missing"):
            execution.paid_entry(entry, phase, None, None, None)
    assert not entry.evidence.exists()


def test_exposed_namespace_preserves_every_original_label_and_unavailable_row() -> None:
    entry = execution.load_entry()
    original = execution.read_json(
        execution.ROOT / "docs/evaluations/r2/member-grounding-exposed-v1.json"
    )
    current = entry.specs["exposed"]
    assert current["queries"] == original["queries"]
    assert current["unavailable_inputs"] == original["unavailable_inputs"]
    assert {t["id"] for t in current["topics"]}.isdisjoint(t["id"] for t in original["topics"])
    assert {
        q["article_id"] for q in current["queries"] if q["exposure_origin"] == "previously_blind"
    } == {9192, 9051, 9125, 9182, 9098, 8981}


def test_minimal_real_plan_preserves_v6_fixtures_and_exact_failure_boundaries() -> None:
    entry = execution.load_entry()
    spec = entry.specs["challenge"]
    originals = execution.read_json(
        execution.ROOT / "docs/acceptance/r2-06-selection/challenges.json"
    )
    packets = {
        t["id"]: t["payload"]
        for t in json.loads(gzip.decompress((execution.ROOT / originals["source"]).read_bytes()))
    }
    assert len(originals["cases"]) == 17 and len(spec["cases"]) == 19
    assert sum(c["physical_audit_limit"] for c in spec["cases"]) == 23
    semantics = [c for c in spec["cases"] if c["expected_boundary"] == "semantic"]
    assert {c["source_case_id"] for c in semantics} == {
        c["id"] for c in originals["cases"] if c["expected_boundary"] == "semantic"
    }
    for case in spec["cases"]:
        packet = copy.deepcopy(packets[case["task_id"]])
        packet["contract"] = member_contract()
        if case["expected_boundary"] == "schema":
            with pytest.raises(ValueError):
                MemberDecision.model_validate(case["decision"])
        else:
            decision = MemberDecision.model_validate(case["decision"])
            if case["expected_boundary"] == "mechanical":
                with pytest.raises(ValueError):
                    validate_selection(packet, decision)
            else:
                assert validate_selection(packet, decision)
    race = [c for c in spec["cases"] if c.get("cas_competition_group")]
    assert len({c["article_id"] for c in race}) == 2 and len({c["topic_id"] for c in race}) == 1
    replay = next(c for c in spec["cases"] if c["id"] == "old-protocol-replay")
    physical = json.loads(
        gzip.decompress(
            (
                execution.ROOT / "docs/acceptance/r2-06-grounding/physical-requests.json.gz"
            ).read_bytes()
        )
    )
    original = next(r for r in physical if r["id"] == replay["retained_physical_request_id"])
    assert replay["decision"] == json.loads(
        original["response_payload"]["choices"][0]["message"]["content"]
    )
    assert replay["physical_audit_limit"] == 0 and replay["expected_boundary"] == "schema"


def test_positive_controls_preserve_whole_query_contribution_and_announcement_roles() -> None:
    entry = execution.load_entry()
    cases = {c["id"]: c for c in entry.specs["challenge"]["cases"]}
    queries = {q["article_id"]: q for q in entry.specs["exposed"]["queries"]}
    france = next(t["key"] for t in entry.specs["exposed"]["topics"] if 8868 in t["anchors"])
    for identity in ("cas-race-a", "cas-race-b"):
        case = cases[identity]
        decision = MemberDecision.model_validate(case["decision"])
        assert decision.identity == "same_occurrence" and decision.contribution == "report"
        assert queries[case["article_id"]]["expected_associations"][france] == ["same_event"]
        assert decision.relation.time == "compatible"
        for facts in (decision.query_facts, decision.anchor_facts):
            known = [f.time for f in facts if f.time.status == "known"]
            assert known and all(
                t.role == "occurrence" and t.precision == "relative" for t in known
            )
        police = decision.anchor_facts[1]
        for role, expected in (
            (police.subject, "riot police"),
            (police.action, "deployed"),
            (police.object, "tear gas and water cannons"),
        ):
            span = role.spans[0]
            assert police.citations[span.citation_index].quote[span.start : span.end] == expected
    control = cases["analysis-contribution-control"]["decision"]
    for identity in ("analysis-contribution-control", "analysis-as-report", "stale-audit-replay"):
        decision = cases[identity]["decision"]
        for owner in ("query_facts", "anchor_facts"):
            assert decision[owner] == control[owner]
            fact = decision[owner][0]
            quote = fact["citations"][0]["quote"]
            action = fact["action"]["spans"][0]
            assert quote[action["start"] : action["end"]] == "\u901a\u62a5"
            assert fact["subject"]["spans"][0] == {"citation_index": 0, "start": 0, "end": 10}
            assert fact["time"]["role"] == "occurrence"
            assert fact["time"]["precision"] == "month_day"
    assert control["contribution"] == "opinion"
    assert cases["analysis-as-report"]["decision"]["contribution"] == "report"
    assert cases["analysis-as-report"]["rejection_target"] == "contribution"


def synthetic_authority(tmp_path: Path) -> tuple[execution.Entry, Path, Path]:
    """Temporary synthetic evidence only; never saved as a real review/authority."""

    def save(name: str, value: Any) -> dict[str, str]:
        path = tmp_path / name
        path.write_text(json.dumps(value))
        return {"path": name, "sha256": execution.sha(path)}

    source = save("source.json", {"synthetic": True})
    instruction = save("instruction.json", {"synthetic_user_instruction": True})
    freeze = save("freeze.json", {"files": [source]})
    receipt = save("receipt.json", {"data": {"id": "synthetic-generation", "total_cost": "0.001"}})
    settlement = save(
        "settlement-authority.json",
        {
            "request_id": "synthetic-stopped-request",
            "provider_receipt_sha256": receipt["sha256"],
            "action": "reconcile_identified_request_only",
            "authorized_by": "synthetic-test",
            "user_instruction": instruction,
        },
    )
    exe = {
        "required_source_paths": ["source.json"],
        "stopped_request": {
            "id": "synthetic-stopped-request",
            "provider_generation_id": "synthetic-generation",
        },
    }
    entry = execution.Entry(tmp_path, tmp_path / "registration.json", exe, {})
    review = save(
        "review.json",
        {
            "schema_version": "r206-selection-entry-review-v1",
            "execution_fingerprint": fingerprint(exe),
            "reviewer": "synthetic-reviewer",
            "reviewed_at": datetime.now(UTC).isoformat(),
            **dict.fromkeys(
                (
                    "source_freeze_reviewed",
                    "challenge_expectations_reviewed",
                    "pr_ci_passed",
                    "main_ci_checked",
                    "runtime_deployment_verified",
                    "deployed_member_sources_match",
                    "provider_receipt_provenance_verified",
                ),
                True,
            ),
            "production_enabled": False,
            "source_freeze": freeze,
            "review_evidence": instruction,
            "provider_receipt": receipt,
            "reconciliation_authorization": settlement,
        },
    )
    auth = save(
        "authority.json",
        {
            "schema_version": "r206-selection-paid-authorization-v1",
            "execution_fingerprint": fingerprint(exe),
            "review_sha256": review["sha256"],
            "provider_receipt_sha256": receipt["sha256"],
            "action": "run_registered_phases_once",
            "phases": ["exposed", "challenge"],
            "authorized_by": "synthetic-user",
            "explicit_paid_authorization": True,
            "provider_read_authorized": True,
            "same_cumulative_pool_usd": "0.30",
            "original_evaluation_limit_usd": "1.50",
            "user_instruction": instruction,
            "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
        },
    )
    return entry, tmp_path / review["path"], tmp_path / auth["path"]


def test_detached_authority_is_bound_to_receipt_review_source_and_separate_instruction(
    tmp_path: Path,
) -> None:
    entry, review, authorization = synthetic_authority(tmp_path)
    assert (
        execution.require_authority(entry, review, authorization, "exposed")["total_cost"]
        == "0.001"
    )
    value = execution.read_json(authorization)
    value["explicit_paid_authorization"] = False
    authorization.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="explicit bounded paid authorization"):
        execution.require_authority(entry, review, authorization, "exposed")
    entry, review, authorization = synthetic_authority(tmp_path)
    (tmp_path / "source.json").write_text("changed after review")
    with pytest.raises(ValueError, match="changed"):
        execution.require_authority(entry, review, authorization, "exposed")


def test_missing_provider_fee_cannot_be_inferred_from_404_or_usage_delta(tmp_path: Path) -> None:
    entry, review, authorization = synthetic_authority(tmp_path)
    path = tmp_path / "receipt.json"
    path.write_text(
        json.dumps({"http_status": 404, "data": {"id": "synthetic-generation"}, "usage_delta": 0})
    )
    value = execution.read_json(review)
    value["provider_receipt"]["sha256"] = execution.sha(path)
    review.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="per-request cost receipt"):
        execution.require_authority(entry, review, authorization, "exposed")


@pytest.mark.parametrize("ceiling", [124, 7])
def test_actual_scoped_v6_chain_keeps_old_task_and_receipts(
    member_db: MemberDB,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    ceiling: int,
) -> None:
    db = member_db
    entry = synthetic_entry(db, tmp_path)
    entry.execution["phases"]["exposed"]["physical_request_limit"] = ceiling
    mock_runner(db, monkeypatch)
    with db.scope() as session:
        old = enqueue(
            session,
            queue="paid",
            kind="topic_review",
            object_key="old:retained",
            article_id=db.article,
            source_id=db.sources[0].id,
            input_fingerprint=fingerprint("retained-old-run"),
            strategy_version="r2-member-v4",
            payload={"retained": True},
        )
        task = session.get(PipelineTask, old)
        assert task
        task.status = "budget_deferred"
    execution.run_exposed(db.billing.engine, entry, Decimal("0.30"), None)
    assert db.judgment().status == "applied" and len(db.calls) == 7
    with db.scope() as session:
        old_task = session.get(PipelineTask, old)
        assert old_task and old_task.status == "budget_deferred" and old_task.attempts == 0
        result = execution.metrics(session, entry)
        assert execution.run_report(session, entry)["complete_exposed_run"]
        assert result["candidate_recall"]["value"] == 1
        assert result["judgment_precision"]["value"] == 1
        assert result["strict_supported_final_coverage"]["value"] == 0
        assert result["unreviewed_applied"] == 1 and not result["strict_basis_review_complete"]
        row = db.judgment()
        assert row.review and len(row.review["audits"]) == 4
        assert len({a["receipt"]["request_id"] for a in row.review["audits"]}) == 4
        findings: dict[str, Any] = {
            "execution_fingerprint": fingerprint(entry.execution),
            "first_output_sha256": execution.sha(entry.first_output("exposed")),
            "reviewer": "synthetic-test-oracle",
            "reviewed_at": datetime.now(UTC).isoformat(),
            "strict_basis_findings": [
                {
                    "judgment_fingerprint": row.input_fingerprint,
                    "fully_supported": True,
                    "issues": [],
                }
            ],
        }
        assert execution.run_report(session, entry, findings)[
            "exposed_numeric_and_strict_basis_pass"
        ]
    assert entry.stop.exists() is (ceiling == 7)
    before = entry.first_output("exposed").read_bytes()
    with pytest.raises(FileExistsError):
        execution.run_exposed(db.billing.engine, entry, Decimal("0.30"), None)
    assert entry.first_output("exposed").read_bytes() == before


def test_unknown_stops_all_phases_and_retains_full_reservation(
    member_db: MemberDB,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db = member_db
    entry = synthetic_entry(db, tmp_path)
    mock_runner(db, monkeypatch)
    db.unknown = True
    execution.run_exposed(db.billing.engine, entry, Decimal("0.30"), None)
    rows = db.billing.requests()
    assert len(rows) == len(db.calls) == 1 and rows[0].status == "usage_unknown"
    assert rows[0].reserved_usd == Decimal("0.001")
    assert execution.read_json(entry.stop)["all_paid_phases_stopped"]
    original = entry.stop.read_bytes()
    execution.mark_stop(entry, "challenge", "must not overwrite", {})
    assert entry.stop.read_bytes() == original
    with db.scope() as session:
        assert execution.stop_reason(session, entry, "challenge", Decimal("0.30"))
        report = execution.run_report(session, entry)
        assert report["complete_exposed_run"] is False
        assert report["exposed_numeric_and_strict_basis_pass"] is False
        assert report["query_chain_receipts"][0]["complete_successful_natural_chain"] is False


@pytest.mark.parametrize(
    ("content", "associated"),
    [
        ("[]", 0),
        ("null", 0),
        (None, 0),
        ([], 0),
        ({}, 0),
        ('{"identity":"same_occurrence","contribution":"report","certainty":"certain"}', 1),
    ],
)
def test_malformed_first_response_remains_a_failure_without_crashing_report(
    member_db: MemberDB,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    content: Any,
    associated: int,
) -> None:
    db = member_db
    entry = synthetic_entry(db, tmp_path)
    mock_runner(db, monkeypatch)
    db.truncate = True
    execution.run_exposed(db.billing.engine, entry, Decimal("0.30"), None)
    with db.scope() as session:
        first = session.scalar(select(BilledRequest).where(BilledRequest.stage == "topic_judgment"))
        assert first
        first.response_payload = {"choices": [{"message": {"content": content}}]}
        session.flush()
        result = execution.metrics(session, entry)
        assert result["schema_valid_first_physical_attempts"] == {
            "numerator": 0,
            "denominator": 1,
            "value": 0,
        }
        assert result["judgment_precision"]["denominator"] == associated
        assert result["strict_supported_final_coverage"]["value"] == 0
        assert not execution.run_report(session, entry)["exposed_numeric_and_strict_basis_pass"]
    assert len(db.calls) == 3


def test_one_judgment_failure_cannot_retry_or_enter_audits(
    member_db: MemberDB,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db = member_db
    entry = synthetic_entry(db, tmp_path)
    mock_runner(db, monkeypatch)
    db.truncate = True
    execution.run_exposed(db.billing.engine, entry, Decimal("0.30"), None)
    assert len(db.calls) == 3
    assert [r.stage for r in db.billing.requests()] == [
        "topic_embedding",
        "topic_embedding",
        "topic_judgment",
    ]
    with db.scope() as session:
        judge = session.scalar(select(PipelineTask).where(PipelineTask.kind == "topic_judge"))
        assert judge and judge.max_attempts == judge.attempts == 1 and judge.status == "failed"
        assert session.scalar(select(MemberJudgment)) is None


def test_cumulative_phase_ceiling_counts_historical_calls_and_fences_other_phase(
    member_db: MemberDB,
    tmp_path: Path,
) -> None:
    entry = synthetic_entry(member_db, tmp_path)
    entry.execution["phases"]["exposed"]["physical_request_limit"] = 0
    with member_db.scope() as session:
        assert "phase physical" in str(
            execution.stop_reason(session, entry, "challenge", Decimal("0.30"))
        )
    entry.execution["phases"]["exposed"]["previous_physical_requests"] = 19
    with member_db.scope() as session, pytest.raises(BudgetExceeded, match="historical phase"):
        execution.phase_count(session, entry, "exposed")


@pytest.mark.parametrize("ceiling", [36, 12, 11])
def test_real_review_replay_and_two_query_cas_race_use_existing_pipeline(
    member_db: MemberDB,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    ceiling: int,
) -> None:
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
    entry = synthetic_entry(db, tmp_path)
    cases: list[dict[str, Any]] = []
    with db.scope() as session:
        for name, article, topic in [
            ("control", db.article, db.topic),
            ("replay", db.article, replay),
            ("race-a", db.article, race),
            ("race-b", other_id, race),
        ]:
            query = current_input(session, article, db.sources, datetime.now(UTC))
            candidate = topic_candidate(session, str(topic), db.sources, datetime.now(UTC))
            decision = decision_for_prompt(
                {
                    "query": project_material(query, "query"),
                    "candidate": {
                        "topic": {
                            "anchors": [
                                {
                                    "snapshot": project_material(
                                        candidate["anchors"][0]["snapshot"], "anchor"
                                    )
                                }
                            ]
                        }
                    },
                }
            )
            case = {
                "id": name,
                "article_id": article,
                "topic_id": str(topic),
                "decision": decision,
                "expected_boundary": "control",
                "expected_status": "applied",
                "physical_audit_limit": 4,
            }
            if name == "replay":
                case.update(
                    replay_actual_review_from="control",
                    expected_status="rejected",
                    physical_audit_limit=0,
                )
            if name.startswith("race"):
                case["cas_competition_group"] = "two-actual-reviews"
            cases.append(case)
    value = entry.specs["exposed"]
    value.update(
        id="synthetic-selection:challenge",
        topics=[{"id": str(t)} for t in (db.topic, replay, race)],
        queries=[{"article_id": i} for i in (db.article, other_id)],
        cases=cases,
    )
    entry.specs["challenge"] = value
    entry.specs.pop("exposed")
    entry.execution["phases"] = {
        "challenge": {"physical_request_limit": ceiling, "previous_physical_requests": 0}
    }
    mock_runner(db, monkeypatch)
    execution.run_challenges(db.billing.engine, entry, Decimal("0.30"), None)
    with db.scope() as session:
        report = execution.challenge_report(session, entry)
    assert report["pass"] is (ceiling >= 12)
    assert report["actual_cas_competition_pass"] is (ceiling >= 12)
    assert entry.stop.exists() is (ceiling <= 12)
    assert report["natural_quality_credit"] is False


def test_receipt_alone_does_not_settle_or_release_the_stopped_hold(
    member_db: MemberDB,
    tmp_path: Path,
) -> None:
    db = member_db
    identity = db.billing.reserve()
    db.billing.journal.identify(identity, "synthetic-generation", 429)
    db.billing.journal.unknown(identity, "synthetic unknown")
    entry = synthetic_entry(db, tmp_path)
    entry.execution["original_holds"] = []
    with db.scope() as session:
        policy = session.get(BudgetPolicy, 1)
        assert policy
        entry.execution["budget"]["stage_caps_usd"] = dict(policy.stage_caps)
        with pytest.raises(ValueError, match="remains unresolved"):
            execution.require_ledger(
                session, entry, {"id": "synthetic-generation", "total_cost": "0"}
            )
    row = db.billing.requests()[0]
    assert row.status == "usage_unknown" and row.reserved_usd > 0
    assert row.reconciliation is None and not db.calls


def test_read_only_report_does_not_require_live_paid_authority_or_load_keys(
    member_db: MemberDB,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db = member_db
    entry = synthetic_entry(db, tmp_path)
    mock_runner(db, monkeypatch)
    execution.run_exposed(db.billing.engine, entry, Decimal("0.30"), None)

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("report must not read credentials, settings, authority or providers")

    monkeypatch.setattr(execution, "get_settings", forbidden)
    monkeypatch.setattr(execution, "require_authority", forbidden)
    monkeypatch.setattr(execution, "provider_key_status", forbidden)

    def isolated_engine(_: Any) -> Engine:
        return db.billing.engine

    monkeypatch.setattr(execution, "create_engine", isolated_engine)
    monkeypatch.setenv(
        "UNSPUN_DATABASE_URL", "postgresql+psycopg://unspun:unspun@127.0.0.1/" + execution.DATABASE
    )
    report = execution.report_entry(entry)
    assert report["complete_exposed_run"] and not report["exposed_numeric_and_strict_basis_pass"]
    assert report["query_chain_receipts"][0]["complete_successful_natural_chain"]
    original = entry.first_output("exposed").read_text()
    entry.first_output("exposed").write_text(
        original.replace(fingerprint(entry.execution), "wrong")
    )
    with pytest.raises(ValueError, match="provenance"):
        execution.report_entry(entry)


def test_provider_read_is_single_attempt_even_if_later_preparation_fails(
    member_db: MemberDB,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db = member_db
    entry = synthetic_entry(db, tmp_path)
    entry.execution["provider_reads"] = {"base_url": "https://openrouter.ai/api/v1"}
    execution.get_settings().grounding_budget_24h_usd = 1.0
    reads: list[bool] = []

    def authority(*args: Any) -> dict[str, Any]:
        return {"synthetic": True}

    def allowed(*args: Any) -> None:
        return None

    def isolated() -> Engine:
        return db.billing.engine

    def provider(_: httpx.Client) -> dict[str, Any]:
        reads.append(True)
        return {"limit_remaining": "1.50"}

    def failed_seed(*args: Any) -> None:
        raise ValueError("synthetic seeding interruption")

    monkeypatch.setattr(execution, "require_authority", authority)
    monkeypatch.setattr(execution, "require_original_engine", isolated)
    monkeypatch.setattr(execution, "require_ledger", allowed)
    monkeypatch.setattr(execution, "require_exact_inputs", allowed)
    monkeypatch.setattr(execution, "provider_key_status", provider)
    monkeypatch.setattr(execution, "seed_topics", failed_seed)
    with pytest.raises(ValueError, match="seeding interruption"):
        execution.paid_entry(entry, "exposed", None, None, None)
    with pytest.raises(ValueError, match="no overwrite or resume"):
        execution.paid_entry(entry, "exposed", None, None, None)
    assert reads == [True]
    assert not db.calls and not db.billing.requests()
