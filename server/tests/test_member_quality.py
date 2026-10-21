"""Frozen real-input admission and persistent pooled request guards; no external HTTP."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.orm import Session

from tests.test_member_processing import MemberDB
from unspun.core.billing import BudgetExceeded
from unspun.core.content_publication import qualified_item
from unspun.core.llm import LlmClient, LlmError
from unspun.core.sources import load_sources
from unspun.evaluation import member_quality as quality
from unspun.evaluation.member_quality import MemberBatchJournal, seed_packages, seed_topics
from unspun.pipeline.member_processing import MemberHandler
from unspun.pipeline.r1_worker import Blocked

pytest_plugins = ["tests.test_member_processing"]


def spec(db: MemberDB, **budget: Any) -> dict[str, Any]:
    return {
        "id": "synthetic-batch",
        "queries": [{"article_id": db.article, "split": "regression"}],
        "budget": {
            "physical_request_limit": 20,
            "stage_physical_limits": {
                "topic_embedding": 10,
                "topic_judgment": 5,
                "topic_review": 5,
            },
            **budget,
        },
    }


def handler(db: MemberDB, value: dict[str, Any], cap: str = "0.20") -> MemberHandler:
    journal = MemberBatchJournal(db.billing.engine, value, Decimal(cap))
    return MemberHandler(
        {s.id: s for s in db.sources},
        scope=db.scope,
        client_factory=lambda context: LlmClient(
            context=context,
            transport=httpx.MockTransport(db.transport),
            journal_factory=lambda _: journal,
        ),
    )


def test_call_limit_reconstructed_after_client_restart(member_db: MemberDB) -> None:
    db = member_db
    value = spec(db, physical_request_limit=1)
    db.enqueue()
    lease = db.claim("topic_recall")
    for _ in range(2):
        with pytest.raises(Blocked, match="cap reached"):
            handler(db, value).run(lease)
    assert len(db.calls) == len(db.billing.requests()) == 1


def test_pooled_cap_includes_actual_prior_fees_and_new_reservation(member_db: MemberDB) -> None:
    db = member_db
    db.enqueue()
    with pytest.raises(Blocked, match="pooled budget"):
        handler(db, spec(db), "0.001").run(db.claim("topic_recall"))
    assert len(db.calls) == 1
    assert db.billing.requests()[0].status == "responded"


def test_new_unknown_stops_further_paid_requests_and_preserves_hold(member_db: MemberDB) -> None:
    db = member_db
    db.unknown = True
    db.enqueue()
    lease = db.claim("topic_recall")
    with pytest.raises(httpx.ReadTimeout):
        handler(db, spec(db)).run(lease)
    db.unknown = False
    with pytest.raises(Blocked, match="new unknown"):
        handler(db, spec(db)).run(lease)
    assert len(db.calls) == 1
    row = db.billing.requests()[0]
    assert row.status == "usage_unknown" and row.reserved_usd == Decimal("0.001")


def test_member_truncation_stops_at_first_physical_request(member_db: MemberDB) -> None:
    db = member_db
    db.enqueue()
    db.step("topic_recall")
    db.truncate = True
    with pytest.raises(LlmError, match="no automatic retry"):
        handler(db, spec(db, physical_request_limit=3)).run(db.claim("topic_judge"))
    assert len(db.calls) == len(db.billing.requests()) == 3
    assert db.billing.requests()[-1].response_payload


def test_real_frozen_admission_does_not_certify_excluded_inputs(db_session: Session) -> None:
    value = quality.registration(require_current_contract=False)
    packages = json.loads((quality.ROOT / "docs/evaluations/r2/member-inputs-v1.json").read_text())
    seed_packages(db_session, packages["packages"])

    eligible: list[int] = []
    for package in packages["packages"]:
        item = qualified_item(
            db_session,
            package["article"]["id"],
            preview=False,
            as_of=datetime.now(UTC),
            sources=load_sources(),
        )
        if item:
            eligible.append(item.article.id)
    assert len(eligible) == 22
    assert {8844, 8847, 8869, 8888, 8900, 8907, 8909, 8910, 8916, 8919}.isdisjoint(eligible)
    seed_topics(db_session, value, load_sources())
    with pytest.raises(ValueError, match="no overwrite"):
        seed_packages(db_session, packages["packages"])


def test_batch_uses_actual_handler_queue_and_cas(
    member_db: MemberDB, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db = member_db
    original = LlmClient
    monkeypatch.setattr(quality, "load_sources", lambda: db.sources)
    monkeypatch.setattr(quality, "EVIDENCE", tmp_path)

    def client(**kwargs: Any) -> LlmClient:
        kwargs["transport"] = httpx.MockTransport(db.transport)
        return original(**kwargs)

    monkeypatch.setattr(quality, "LlmClient", client)
    quality.run_batch(db.billing.engine, spec(db), Decimal("0.20"), None)
    records = [
        json.loads(line) for line in (tmp_path / "first-run.ndjson").read_text().splitlines()
    ]
    assert records[-1]["event"] == "complete"
    assert db.judgment().status == "applied"
    assert len(db.calls) == 7


def test_allocation_retains_original_known_cost_and_unknown_holds(member_db: MemberDB) -> None:
    from datetime import UTC, datetime

    from unspun.core.billing_models import BilledRequest
    from unspun.core.models import LlmUsage

    db = member_db
    with db.scope() as session:
        session.add(LlmUsage(purpose="summary", model="synthetic", cost_usd=1.25))
        session.add(
            BilledRequest(
                id="retained-unknown",
                purpose="summary",
                stage="card",
                phase="generate",
                model="synthetic",
                request_fingerprint="retained",
                price_version="synthetic",
                reserved_usd=Decimal("0.10"),
                status="usage_unknown",
                started_at=datetime.now(UTC),
            )
        )
    value = spec(db)
    value["budget"].update(
        batch_limit_usd="0.20",
        stage_caps_usd={
            "topic_embedding": "0.02",
            "topic_judgment": "0.08",
            "topic_review": "0.20",
        },
    )
    with db.scope() as session:
        result = quality.allocate(session, value, {"limit_remaining": "0.18"})
        assert Decimal(result["effective_cap_usd"]) == Decimal("0.08")
        assert result["before"]["accounting"] == result["after"]["accounting"]
        old = session.get(BilledRequest, "retained-unknown")
        assert old and old.status == "usage_unknown" and old.reserved_usd == Decimal("0.10")


def test_concurrent_reservations_share_one_physical_cap(member_db: MemberDB) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from unspun.core.billing import CallContext

    db = member_db
    db.enqueue()
    lease = db.claim("topic_recall")
    gate = Barrier(2)
    value = spec(db, physical_request_limit=1)

    def reserve_once(index: int) -> str:
        gate.wait(timeout=5)
        journal = MemberBatchJournal(db.billing.engine, value, Decimal("0.20"))
        try:
            journal.reserve(
                purpose="embedding",
                model="qwen/qwen3-embedding-8b",
                request={"input": ["synthetic"]},
                context=CallContext(
                    stage="topic_embedding",
                    phase="embed",
                    logical_key="synthetic-" + str(index),
                    lease=lease,
                ),
            )
            return "reserved"
        except BudgetExceeded:
            return "blocked"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve_once, range(2)))
    assert sorted(results) == ["blocked", "reserved"]
    assert len(db.billing.requests()) == 1 and not db.calls


def test_first_technical_failure_is_retained_without_execution_retry(
    member_db: MemberDB, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db = member_db
    original = LlmClient
    monkeypatch.setattr(quality, "load_sources", lambda: db.sources)
    monkeypatch.setattr(quality, "EVIDENCE", tmp_path)

    def invalid(request: httpx.Request) -> httpx.Response:
        response = db.transport(request)
        payload = response.json()
        if not request.url.path.endswith("embeddings"):
            payload["choices"][0]["message"]["content"] = '{"invalid":true}'
        return httpx.Response(200, json=payload)

    def client(**kwargs: Any) -> LlmClient:
        kwargs["transport"] = httpx.MockTransport(invalid)
        return original(**kwargs)

    monkeypatch.setattr(quality, "LlmClient", client)
    quality.run_batch(db.billing.engine, spec(db), Decimal("0.20"), None)
    records = [
        json.loads(line) for line in (tmp_path / "first-run.ndjson").read_text().splitlines()
    ]
    assert records[-1]["event"] == "complete"
    assert any(
        t["status"] == "failed" for r in records if r["event"] == "checkpoint" for t in r["tasks"]
    )
    assert len(db.calls) == 3


def test_existing_url_is_retained_and_requires_frozen_exclusion(db_session: Session) -> None:
    from sqlalchemy import func, select

    from unspun.core.models import Article

    packages = json.loads((quality.ROOT / "docs/evaluations/r2/member-inputs-v1.json").read_text())[
        "packages"
    ]
    package = next(p for p in packages if p["article"]["id"] == 8877)
    old = Article(
        url=package["article"]["url"],
        title="Retained earlier material version",
        source_id="douban-book",
        processing_track="r1",
    )
    db_session.add(old)
    db_session.flush()
    with pytest.raises(ValueError, match="URL already exists"):
        seed_packages(db_session, packages)
    assert db_session.scalar(select(func.count()).select_from(Article)) == 1
    seed_packages(db_session, packages, exclude_ids=frozenset({8877}))
    assert db_session.get(Article, 8877) is None
    assert old.title == "Retained earlier material version" and old.current_material_id is None


def test_unavailable_input_never_initiates_a_paid_task(
    member_db: MemberDB, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db = member_db
    value = spec(db)
    value["unavailable_inputs"] = [{"article_id": db.article, "reason": "frozen conflict"}]
    monkeypatch.setattr(quality, "load_sources", lambda: db.sources)
    monkeypatch.setattr(quality, "EVIDENCE", tmp_path)
    quality.run_batch(db.billing.engine, value, Decimal("0.20"), None)
    records = [
        json.loads(line) for line in (tmp_path / "first-run.ndjson").read_text().splitlines()
    ]
    assert any(r["event"] == "unavailable" for r in records)
    assert records[-1]["event"] == "complete" and not db.calls and not db.billing.requests()
