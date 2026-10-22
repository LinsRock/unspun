"""Manual corrections use authenticated CAS and never enqueue model work."""

from collections.abc import AsyncIterator, Generator
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_content_feed import NOW, TEXT, ready
from tests.test_topics import derive, ref, setup, update
from unspun.api.admin import topics
from unspun.api.admin.auth import require_admin_identity
from unspun.api.app import app
from unspun.api.events import get_db
from unspun.core.billing_models import BilledRequest
from unspun.core.member_models import MemberJudgment
from unspun.core.models import LlmUsage
from unspun.core.sources import Source, load_sources
from unspun.core.task_models import PipelineTask, TaskAttempt
from unspun.core.tasks import enqueue
from unspun.core.topic_models import Topic, TopicChange, TopicMember


@pytest.fixture
def sources(monkeypatch: pytest.MonkeyPatch) -> list[Source]:
    source = next(s for s in load_sources() if s.id == "xinhua")
    assert source.r1
    result = [
        source.model_copy(
            update={
                "discovery_owner": "r1",
                "legacy_enabled": False,
                "r1": source.r1.model_copy(update={"publish": True, "publish_scopes": None}),
            }
        )
    ]
    monkeypatch.setattr(topics, "load_sources", lambda: result)
    return result


@pytest.fixture
async def client(db_session: Session, sources: list[Source]) -> AsyncIterator[httpx.AsyncClient]:
    def read() -> Generator[Session]:
        yield db_session

    def write() -> Generator[Session]:
        with db_session.begin_nested():
            yield db_session

    app.dependency_overrides[require_admin_identity] = lambda: "verified-admin@example.org"
    app.dependency_overrides[get_db] = read
    app.dependency_overrides[topics.get_write_db] = write
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://localhost",
            headers={"Origin": "http://localhost"},
        ) as value:
            yield value
    finally:
        for dependency in (require_admin_identity, get_db, topics.get_write_db):
            app.dependency_overrides.pop(dependency, None)


def correction(article_id: int, material_id: int, revision: int) -> dict[str, Any]:
    return {
        "mutation_id": str(uuid4()),
        "expected_revision": revision,
        "reason": "Correct the relationship after reading the original",
        "article_id": article_id,
        "material_id": material_id,
        "relation": "background",
        "basis": "The original provides background for this topic",
        "evidence": [
            {
                "article_id": article_id,
                "material_id": material_id,
                "paragraph": 0,
                "quote": TEXT[:100],
                "voice": "reported",
            }
        ],
    }


@pytest.mark.anyio
async def test_all_topic_routes_require_admin_identity() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        for path in (
            "topics",
            f"topics/{uuid4()}",
            "member-contents/1",
            "member-tasks",
            "member-tasks/1",
        ):
            assert (await client.get(f"/api/admin/{path}")).status_code == 503
        assert (await client.post("/api/admin/topics", json={})).status_code == 503


@pytest.mark.anyio
async def test_topic_creation_origin_identity_and_idempotency(
    client: httpx.AsyncClient, db_session: Session
) -> None:
    body = {
        "topic_id": str(uuid4()),
        "mutation_id": str(uuid4()),
        "reason": "Create after reading the source",
        "kind": "issue",
        "title": "  Literal %_ topic  ",
        "domains": ["science"],
    }
    for origin in ("https://evil.example", "null", "http://localhost/path"):
        response = await client.post("/api/admin/topics", json=body, headers={"Origin": origin})
        assert response.status_code == 403
    request = client.build_request("POST", "/api/admin/topics", json=body)
    del request.headers["Origin"]
    assert (await client.send(request)).status_code == 403
    for extra in ({"actor": "spoofed"}, {"expected_revision": 0}, {"status": "archived"}):
        assert (await client.post("/api/admin/topics", json={**body, **extra})).status_code == 422
    first = await client.post("/api/admin/topics", json=body)
    assert first.status_code == 201
    assert (await client.post("/api/admin/topics", json=body)).json() == first.json()
    assert first.json()["revision"] == 1
    assert (
        await client.post("/api/admin/topics", json={**body, "mutation_id": str(uuid4())})
    ).status_code == 409
    duplicate_domains = {**body, "topic_id": str(uuid4()), "domains": ["science", "science"]}
    assert (await client.post("/api/admin/topics", json=duplicate_domains)).status_code == 422
    listed = (await client.get("/api/admin/topics", params={"q": "%_"})).json()
    assert listed["total"] == 1 and listed["items"][0]["title"] == "Literal %_ topic"
    assert listed["items"][0]["active_member_count"] == 0
    detail = (await client.get(f"/api/admin/topics/{body['topic_id']}")).json()
    assert detail["changes"][0]["actor"] == "verified-admin@example.org"
    assert detail["changes"][0]["reason"] == body["reason"]
    assert db_session.scalar(select(func.count()).select_from(PipelineTask)) == 0
    assert db_session.scalar(select(func.count()).select_from(BilledRequest)) == 0


@pytest.mark.anyio
async def test_correction_replay_conflict_and_retained_invalidation(
    client: httpx.AsyncClient, db_session: Session, sources: list[Source]
) -> None:
    topic_id, article = setup(db_session, sources)
    old_update = update(db_session, topic_id, article, sources)
    old_derivation = derive(db_session, topic_id, article, sources)
    detail_url = f"/api/admin/topics/{topic_id}"
    before = (await client.get(detail_url)).json()
    assert before["updates"][0]["check"]["valid"]
    assert before["derivations"][0]["check"]["valid"]
    original = (await client.get(f"/api/admin/member-contents/{article.id}")).json()
    assert original["article_id"] == article.id
    assert original["paragraphs"] == [
        {
            "index": 0,
            "text": TEXT,
            "voice": None,
            "allowed_voices": ["reported", "author", "question", "description"],
        }
    ]
    request = correction(article.id, original["material_id"], before["topic"]["revision"])
    response = await client.post(f"{detail_url}/members", json=request)
    assert response.status_code == 200
    revision = response.json()["revision"]
    assert revision == before["topic"]["revision"] + 1
    after = (await client.get(detail_url)).json()
    assert after["members"][0]["decision_version"] == topics.MANUAL_VERSION
    assert after["members"][0]["relation"] == "background"
    assert after["members"][0]["check"]["valid"]
    assert after["changes"][0]["before"]["relation"] == "report"
    assert after["changes"][0]["after"]["relation"] == "background"
    assert after["changes"][0]["actor"] == "verified-admin@example.org"
    assert not after["updates"][0]["check"]["valid"]
    assert not after["derivations"][0]["check"]["valid"]
    assert after["updates"][0]["revision"] == old_update.revision
    assert after["derivations"][0]["revision"] == old_derivation.revision
    assert after["derivations"][0]["contract_verification"] == "stored_contract_only"
    # A network-ambiguous retry returns its original receipt, including after a later edit.
    assert (await client.post(f"{detail_url}/members", json=request)).json() == response.json()
    assert (
        await client.post(
            f"{detail_url}/members", json={**request, "basis": "Changed same operation"}
        )
    ).status_code == 409
    assert (
        await client.post(f"{detail_url}/members", json={**request, "mutation_id": str(uuid4())})
    ).status_code == 409
    removal = {
        "mutation_id": str(uuid4()),
        "expected_revision": revision,
        "reason": "Remove the mistaken association",
    }
    removed = await client.post(f"{detail_url}/members/{article.id}/remove", json=removal)
    assert removed.status_code == 200
    assert (await client.post(f"{detail_url}/members", json=request)).json() == response.json()
    final = (await client.get(detail_url)).json()
    assert final["members"][0]["active"] is False
    assert final["members"][0]["check"]["reasons"] == ["member_removed"]
    assert final["changes"][0]["before"]["active"] is True
    assert final["changes"][0]["after"]["active"] is False
    assert final["topic"]["revision"] == revision + 1
    assert db_session.scalar(select(func.count()).select_from(PipelineTask)) == 0
    assert db_session.scalar(select(func.count()).select_from(BilledRequest)) == 0


@pytest.mark.anyio
async def test_invalid_evidence_and_forged_contract_cannot_write(
    client: httpx.AsyncClient, db_session: Session, sources: list[Source]
) -> None:
    topic_id, article = setup(db_session, sources)
    other = ready(db_session)
    assert article.current_material_id and other.current_material_id
    request = correction(article.id, article.current_material_id, 2)
    url = f"/api/admin/topics/{topic_id}/members"
    cases = [
        {**request, "material_id": other.current_material_id},
        {**request, "evidence": [ref(other).model_dump()]},
        {**request, "evidence": [{**request["evidence"][0], "quote": "Absent from original"}]},
        {**request, "evidence": [{**request["evidence"][0], "paragraph": 1}]},
        {**request, "evidence": [{**request["evidence"][0], "voice": "invented"}]},
        {**request, "reason": "   "},
        {**request, "actor": "forged"},
        {**request, "decision_version": "reviewed-model"},
    ]
    for invalid in cases:
        response = await client.post(url, json=invalid)
        assert response.status_code == 422, response.text
    article.current_material_id = None
    db_session.flush()
    assert (await client.post(url, json=request)).status_code == 422
    assert (await client.get(f"/api/admin/member-contents/{article.id}")).status_code == 422
    assert (await client.get("/api/admin/member-contents/2147483647")).status_code == 404
    topic = db_session.get(Topic, str(topic_id))
    assert topic and topic.revision == 2
    assert db_session.scalar(select(func.count()).select_from(TopicChange)) == 2
    member = db_session.get(TopicMember, (str(topic_id), article.id))
    assert member and member.relation == "report"


@pytest.mark.anyio
async def test_task_receipts_keep_unknown_cost_separate_and_totals_unbounded(
    client: httpx.AsyncClient, db_session: Session, sources: list[Source]
) -> None:
    topic_id, article = setup(db_session, sources)

    def task(kind: str, payload: dict[str, Any]) -> int:
        return enqueue(
            db_session,
            queue="paid",
            kind=kind,
            object_key=f"synthetic-admin-{kind}",
            input_fingerprint=str(uuid4()),
            strategy_version="synthetic-v1",
            payload=payload,
            article_id=article.id,
            max_attempts=1,
        )

    packet = {"candidate": {"topic": {"id": str(topic_id)}}}
    recall = task("topic_recall", {"topics": [{"id": str(topic_id), "revision": 2}]})
    task("topic_recall", {"topics": [{"id": str(uuid4()), "revision": 1}]})
    judge = task("topic_judge", packet)
    review = task("topic_review", {**packet, "decision_key": "synthetic-decision"})
    unrelated = task("process_card", {})
    db_session.add(
        MemberJudgment(
            input_fingerprint="synthetic-decision",
            task_id=judge,
            article_id=article.id,
            topic_id=str(topic_id),
            topic_revision=2,
            input_snapshot={"original": "retained"},
            decision={"classification": "background"},
            review={"accepted": False, "reason": "Synthetic rejection"},
            status="rejected",
        )
    )
    attempt = TaskAttempt(
        task_id=review,
        claim_version=1,
        worker="synthetic",
        started_at=NOW,
        lease_until=NOW + timedelta(seconds=120),
        ended_at=NOW,
        status="failed",
        error="Synthetic provider timeout",
    )
    usage = LlmUsage(purpose="topic_review", model="synthetic", cost_usd=0.0123)
    recall_usage = LlmUsage(purpose="topic_embedding", model="synthetic", cost_usd=0.000012)
    db_session.add_all([attempt, usage, recall_usage])
    db_session.flush()
    db_session.add(
        BilledRequest(
            id="synthetic-admin-recall",
            purpose="topic_embedding",
            stage="topic_recall",
            phase="query_vector",
            model="synthetic",
            request_fingerprint="synthetic-recall",
            price_version="synthetic",
            reserved_usd=Decimal("0.0001"),
            status="responded",
            task_id=recall,
            article_id=article.id,
            usage_id=recall_usage.id,
            started_at=NOW,
        )
    )
    for index in range(topics.RECORD_LIMIT + 2):
        known = index == 0
        db_session.add(
            BilledRequest(
                id=f"synthetic-admin-{index}",
                purpose="topic_review",
                stage="topic_review",
                phase="query_support",
                model="synthetic",
                request_fingerprint=str(index),
                price_version="synthetic",
                reserved_usd=Decimal("0.03"),
                status="responded" if known else "usage_unknown",
                task_id=review,
                task_attempt_id=attempt.id,
                article_id=article.id,
                usage_id=usage.id if known else None,
                provider_generation_id="synthetic-provider-id" if known else None,
                started_at=NOW + timedelta(seconds=index),
                error=None if known else "Unknown fee",
            )
        )
    db_session.flush()
    listed = (
        await client.get("/api/admin/member-tasks", params={"topic_id": str(topic_id)})
    ).json()
    assert {row["id"] for row in listed["items"]} == {recall, judge, review}
    assert listed["total"] == 3
    recall_detail = (await client.get(f"/api/admin/member-tasks/{recall}")).json()
    assert recall_detail["calls"][0]["stage"] == "topic_recall"
    assert recall_detail["calls"][0]["phase"] == "query_vector"
    assert Decimal(recall_detail["costs"]["known_usd"]) == Decimal("0.000012")
    assert (await client.get(f"/api/admin/member-tasks/{unrelated}")).status_code == 404
    detail = (await client.get(f"/api/admin/member-tasks/{review}")).json()
    assert detail["judgments"][0]["task_id"] == judge
    assert detail["judgments"][0]["review"]["accepted"] is False
    assert detail["attempts"][0]["id"] == attempt.id
    assert detail["calls_total"] == 102 and len(detail["calls"]) == topics.RECORD_LIMIT
    assert Decimal(detail["costs"]["known_usd"]) == Decimal("0.0123")
    assert Decimal(detail["costs"]["held_usd"]) == Decimal("3.03")
    assert detail["costs"]["unknown_requests"] == 101
    assert detail["costs"]["physical_requests"] == 102
    assert all(row["known_cost_usd"] is None for row in detail["calls"])
    assert all(Decimal(row["reserved_usd"]) == Decimal("0.03") for row in detail["calls"])
    assert (await client.get("/api/admin/member-tasks?page_size=51")).status_code == 422
    # Viewing history does not settle, retry or create tasks.
    assert db_session.scalar(select(func.count()).select_from(PipelineTask)) == 5
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(BilledRequest)
            .where(BilledRequest.status == "usage_unknown")
        )
        == 101
    )
