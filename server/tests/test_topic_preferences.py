"""R2-09 explicit preferences; all provider-shaped fixtures use MockTransport."""

import threading
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from tests.test_hybrid_topics import build, feed
from tests.test_topic_synthesis import SynthesisDB
from tests.test_topic_synthesis import synthesis_db as synthesis_db
from tests.test_topics import DEFINITION, write
from unspun.api.admin.auth import require_admin_identity
from unspun.api.app import app
from unspun.api.events import get_db
from unspun.api.feed_preferences import get_write_db
from unspun.core.config import Settings, get_settings
from unspun.core.models import ContentMaterial
from unspun.core.reader import InterestTarget, Mutation, mutate, snapshot
from unspun.core.reader_models import (
    ContentFeedback,
    ReaderChange,
    ReaderInterest,
    ReaderRequest,
    ReaderState,
    TopicPreference,
)
from unspun.core.topic_models import Topic

pytest_plugins = ["tests.test_billing"]


@pytest.fixture
def preference_db(
    synthesis_db: SynthesisDB, monkeypatch: pytest.MonkeyPatch
) -> Generator[SynthesisDB]:
    db = synthesis_db
    build(db, monkeypatch)
    monkeypatch.setattr(get_settings(), "r2_topic_preferences_enabled", True)
    monkeypatch.setattr("unspun.core.reader_targets.load_sources", lambda: db.sources)
    yield db
    with db.scope() as session:
        for model in (
            TopicPreference,
            ContentFeedback,
            ReaderInterest,
            ReaderRequest,
            ReaderChange,
            ReaderState,
        ):
            session.execute(delete(model))


def change(
    db: SynthesisDB, kind: str, value: dict[str, Any] | None, *, body: Mutation | None = None
) -> dict[str, Any]:
    with db.scope() as session:
        body = body or Mutation(version=snapshot(session)["version"], mutation_id=uuid4())
        return mutate(
            session, body, kind, {"type": "topic", "id": str(db.topic)}, value, include_topics=True
        )


def test_follow_feedback_modify_revoke_same_candidates_and_cursors(
    preference_db: SynthesisDB,
) -> None:
    db = preference_db
    before = feed(db, sort="recommended")
    original_latest = [i["id"] for i in feed(db)["items"]]
    content_scores = {i["id"]: i["ranking"] for i in before["items"] if i["type"] == "content"}
    first = Mutation(version=0, mutation_id=uuid4())
    operations = [
        ("topic_follow", {"active": True}, 2),
        ("topic_feedback", {"value": "interested"}, 4),
        ("topic_feedback", {"value": "not_interested"}, -3),
        ("topic_feedback", {"value": "interested"}, 4),
        ("topic_feedback", None, 2),
        ("topic_follow", None, 0),
    ]
    for index, (kind, value, score) in enumerate(operations):
        old = feed(db, limit=1)
        result = change(db, kind, value, body=first if index == 0 else None)
        assert result["version"] == index + 1
        with pytest.raises(HTTPException) as stale:
            feed(db, limit=1, cursor=old["next_cursor"])
        assert stale.value.status_code == 409
        current = feed(db, sort="recommended")
        topic = next(i for i in current["items"] if i["type"] == "topic")
        assert topic["ranking"]["score"] == score
        assert topic["ranking"]["important"] is topic["ranking"]["public_attention"] is None
        assert topic["ranking"]["matched_interests"] == []
        assert {
            i["id"]: i["ranking"] for i in current["items"] if i["type"] == "content"
        } == content_scores
        assert [i["id"] for i in feed(db)["items"]] == original_latest
        assert {i["id"] for i in current["items"]} == set(original_latest)
    replay = change(db, "topic_follow", {"active": True}, body=first)
    assert replay["replayed"] and replay["version"] == 6 and replay["topic_preferences"] == []
    with db.scope() as session:
        assert session.scalar(select(func.count()).select_from(ReaderChange)) == 6
        assert session.scalar(select(func.count()).select_from(ReaderRequest)) == 6
        assert snapshot(session)["interests"] == snapshot(session)["feedback"] == []
        history = list(session.scalars(select(ReaderChange).order_by(ReaderChange.version)))
        assert history[2].target == {"type": "topic", "id": str(db.topic)}
        assert history[2].value == {
            "before": {"followed": True, "feedback": "interested"},
            "after": {"followed": True, "feedback": "not_interested"},
        }


def test_noop_is_receipted_and_replay_returns_current_state(preference_db: SynthesisDB) -> None:
    db = preference_db
    request = Mutation(version=0, mutation_id=uuid4())
    empty = change(db, "topic_follow", None, body=request)
    assert empty["unchanged"] and empty["version"] == 0
    with pytest.raises(HTTPException) as reused:
        change(db, "topic_follow", {"active": True}, body=request)
    assert (
        reused.value.status_code == 409
        and cast(dict[str, Any], reused.value.detail)["code"] == "mutation_id_reused"
    )
    change(db, "topic_follow", {"active": True})
    replay = change(db, "topic_follow", None, body=request)
    assert (
        replay["version"] == 1 and replay["replayed"] and replay["topic_preferences"][0]["followed"]
    )
    no_change = Mutation(version=1, mutation_id=uuid4())
    cursor = feed(db, limit=1)["next_cursor"]
    assert change(db, "topic_follow", {"active": True}, body=no_change)["unchanged"]
    assert feed(db, limit=1, cursor=cursor)["items"]
    change(db, "topic_follow", None)
    assert change(db, "topic_follow", {"active": True}, body=no_change)["topic_preferences"] == []


@pytest.mark.parametrize(
    "failure", ["rename", "archived", "material", "source", "publication", "mock"]
)
def test_invalid_target_cannot_publish_but_can_be_revoked(
    preference_db: SynthesisDB, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    db = preference_db
    first = Mutation(version=0, mutation_id=uuid4())
    change(db, "topic_follow", {"active": True}, body=first)
    change(db, "topic_feedback", {"value": "interested"})
    old = feed(db, limit=1)
    with db.scope() as session:
        if failure == "rename":
            write(
                session,
                db.topic,
                DEFINITION.model_copy(update={"title": "Renamed fixture"}),
                db.sources,
            )
        elif failure == "archived":
            topic = session.get(Topic, str(db.topic))
            assert topic
            topic.status = "archived"
        elif failure == "material":
            material = session.scalar(
                select(ContentMaterial).where(ContentMaterial.article_id == db.article)
            )
            assert material
            material.paragraphs = [{"kind": "paragraph", "text": "Changed fixture material"}]
        elif failure == "mock":
            from unspun.core.billing_models import BilledRequest

            request = session.scalar(select(BilledRequest).order_by(BilledRequest.started_at))
            assert request and request.response_payload
            request.response_payload = {**request.response_payload, "unspun_mock": True}
    if failure == "source":
        source = db.sources[0]
        assert source.r1
        db.sources = [
            source.model_copy(update={"r1": source.r1.model_copy(update={"publish": False})})
        ]
    if failure == "publication":
        monkeypatch.setattr(get_settings(), "r2_topic_publication_enabled", False)
    assert not any(i["type"] == "topic" for i in feed(db)["items"])
    with pytest.raises(HTTPException) as stale:
        feed(db, limit=1, cursor=old["next_cursor"])
    assert stale.value.status_code == 409
    with pytest.raises(HTTPException) as rejected:
        change(db, "topic_feedback", {"value": "not_interested"})
    assert rejected.value.status_code == 404
    retained = change(db, "topic_follow", {"active": True}, body=first)
    assert retained["replayed"] and retained["topic_preferences"][0]["target"]["id"] == str(
        db.topic
    )
    after = change(db, "topic_follow", None)
    assert after["topic_preferences"][0]["feedback"] == "interested"
    assert not after["topic_preferences"][0]["followed"]
    assert change(db, "topic_feedback", None)["topic_preferences"] == []
    assert change(db, "topic_follow", {"active": True}, body=first)["topic_preferences"] == []


def test_term_is_not_subscription_and_switch_disables_effect(
    preference_db: SynthesisDB, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = preference_db
    with db.scope() as session:
        topic = session.get(Topic, str(db.topic))
        assert topic
        mutate(
            session,
            Mutation(version=0, mutation_id=uuid4()),
            "interest",
            InterestTarget(kind="term", value=topic.title).model_dump(),
            {"active": True},
        )
        assert snapshot(session, include_topics=True)["topic_preferences"] == []
    change(db, "topic_follow", {"active": True})
    old = feed(db, limit=1)
    monkeypatch.setattr(get_settings(), "r2_topic_preferences_enabled", False)
    with pytest.raises(HTTPException) as stale:
        feed(db, limit=1, cursor=old["next_cursor"])
    assert stale.value.status_code == 409
    topic = next(i for i in feed(db)["items"] if i["type"] == "topic")
    assert "follow_boost" not in topic["ranking"]
    with db.scope() as session:
        assert session.scalar(select(func.count()).select_from(TopicPreference)) == 1
        assert len(snapshot(session)["interests"]) == 1


@pytest.mark.parametrize("same_request", [False, True])
def test_simultaneous_devices_share_cas_and_receipts(
    preference_db: SynthesisDB, same_request: bool
) -> None:
    db = preference_db
    with db.scope() as session:
        session.add(ReaderState(id=1, version=0, sort="recommended"))
    bodies = [Mutation(version=0, mutation_id=uuid4()), Mutation(version=0, mutation_id=uuid4())]
    if same_request:
        bodies[1] = bodies[0]
    barrier = threading.Barrier(2)

    def run(index: int) -> int:
        try:
            with db.scope() as session:
                assert snapshot(session)["version"] == 0
                barrier.wait(timeout=5)
                mutate(
                    session,
                    bodies[index],
                    "topic_follow",
                    {"type": "topic", "id": str(db.topic)},
                    {"active": True},
                )
            return 200
        except HTTPException as error:
            return error.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(run, (0, 1))) == ([200, 200] if same_request else [200, 409])
    with db.scope() as session:
        assert snapshot(session)["version"] == 1
        assert session.scalar(select(func.count()).select_from(ReaderRequest)) == 1
        assert session.scalar(select(func.count()).select_from(ReaderChange)) == 1


@pytest.mark.anyio
async def test_typed_api_and_legacy_compatibility(preference_db: SynthesisDB) -> None:
    db = preference_db

    def session() -> Generator[Session]:
        with db.scope() as s:
            yield s

    app.dependency_overrides[get_db] = session
    app.dependency_overrides[get_write_db] = session
    app.dependency_overrides[require_admin_identity] = lambda: "fixture"
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="https://test",
            headers={"Origin": "https://test"},
        ) as client:
            body = {
                "version": 0,
                "mutation_id": str(uuid4()),
                "target": {"type": "topic", "id": str(db.topic)},
            }
            assert (
                await client.put(
                    "/api/topic-follows", json=body, headers={"Origin": "https://evil.test"}
                )
            ).status_code == 403
            assert (
                await client.put(
                    "/api/topic-follows", json=body, headers={"Sec-Fetch-Site": "cross-site"}
                )
            ).status_code == 403
            for target in (
                {"type": "term", "id": "fixture"},
                {"type": "topic", "id": 1},
                {"type": "content", "id": str(db.article)},
                {"type": "content", "id": True},
                {"id": db.article},
            ):
                assert (
                    await client.put(
                        "/api/target-feedback",
                        json={**body, "target": target, "value": "interested"},
                    )
                ).status_code == 422
            response = await client.put("/api/topic-follows", json=body)
            assert response.status_code == 200 and response.json()["version"] == 1
            old = (await client.get("/api/reader-preferences")).json()
            assert "topic_preferences" not in old and old["interests"] == []
            conflict = await client.put(
                "/api/target-feedback", json={**body, "value": "interested"}
            )
            assert (
                conflict.status_code == 409
                and conflict.json()["detail"]["code"] == "mutation_id_reused"
            )
            content = {
                "version": 1,
                "mutation_id": str(uuid4()),
                "target": {"type": "content", "id": db.article},
                "value": "interested",
            }
            saved = await client.put("/api/target-feedback", json=content)
            assert (
                saved.status_code == 200 and saved.json()["feedback"][0]["content_id"] == db.article
            )
            legacy = {k: v for k, v in content.items() if k != "target"} | {
                "content_id": db.article
            }
            replay = await client.put("/api/feedback", json=legacy)
            assert replay.status_code == 200 and replay.json()["replayed"]
            revoked = await client.request(
                "DELETE",
                "/api/feedback",
                json={"version": 2, "mutation_id": str(uuid4()), "content_id": db.article},
            )
            assert revoked.json()["feedback"] == []
            assert (await client.put("/api/target-feedback", json=content)).json()["feedback"] == []
            assert (await client.get("/api/topic-preferences")).json()["topic_preferences"][0][
                "followed"
            ]
            assert (
                await client.request(
                    "DELETE",
                    "/api/topic-follows",
                    json={**body, "version": 3, "mutation_id": str(uuid4())},
                )
            ).json()["topic_preferences"] == []
    finally:
        for dependency in (get_db, get_write_db, require_admin_identity):
            app.dependency_overrides.pop(dependency, None)


@pytest.mark.anyio
async def test_new_api_default_off_and_requires_identity(db_session: Session) -> None:
    assert not Settings().r2_topic_preferences_enabled
    app.dependency_overrides[get_settings] = lambda: Settings(
        access_team_domain="synthetic.cloudflareaccess.com", access_audience="synthetic"
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="https://test",
            headers={"Origin": "https://test"},
        ) as client:
            assert (await client.get("/api/topic-preferences")).status_code == 401
            app.dependency_overrides[require_admin_identity] = lambda: "fixture"
            assert (await client.get("/api/topic-preferences")).status_code == 404
            for path, target in (
                ("/api/topic-follows", {"type": "topic", "id": str(uuid4())}),
                ("/api/target-feedback", {"type": "content", "id": 1}),
            ):
                body = {"version": 0, "mutation_id": str(uuid4()), "target": target}
                for method in ("PUT", "DELETE"):
                    payload = (
                        {**body, "value": "interested"}
                        if path.endswith("feedback") and method == "PUT"
                        else body
                    )
                    assert (await client.request(method, path, json=payload)).status_code == 404
    finally:
        for dependency in (get_settings, require_admin_identity):
            app.dependency_overrides.pop(dependency, None)


def test_direct_targets_supply_independent_bounded_recall(
    preference_db: SynthesisDB, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace
    from uuid import UUID

    from tests.test_topics import member
    from unspun.core.hybrid_contracts import HybridRules
    from unspun.core.models import Article
    from unspun.core.topic_synthesis import MANUAL_VERSION

    db = preference_db
    control = replace(db, topic=UUID(int=1))
    with db.scope() as session:
        write(session, control.topic, DEFINITION, db.sources)
        for identity in (db.article, db.other):
            article = session.get(Article, identity)
            assert article
            write(
                session, control.topic, member(article, decision_version=MANUAL_VERSION), db.sources
            )
    build(control, monkeypatch)
    monkeypatch.setattr(
        "unspun.core.hybrid_feed.hybrid_rules", lambda: HybridRules(topic_lane_limit=1)
    )
    assert {i["id"] for i in feed(db)["items"] if i["type"] == "topic"} == {str(control.topic)}
    for kind, value in (
        ("topic_follow", {"active": True}),
        ("topic_feedback", {"value": "interested"}),
    ):
        change(db, kind, value)
        result = feed(db)
        assert {i["id"] for i in result["items"] if i["type"] == "topic"} == {
            str(control.topic),
            str(db.topic),
        }
        other = next(i for i in result["items"] if i["id"] == str(control.topic))
        assert other["ranking"]["score"] == 0 and not other["ranking"]["followed"]
        assert result["recall"]["topic_selected_by_lane"]["interest"] == 1
        change(db, kind, None)
        assert {i["id"] for i in feed(db)["items"] if i["type"] == "topic"} == {str(control.topic)}
