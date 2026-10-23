"""R2-08 engineering fixtures; no real signal, model quality or user ratings."""

from collections.abc import Generator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.test_content_feed import NOW, ready
from tests.test_content_feed import enabled_sources as enabled_sources
from unspun.api.admin.auth import require_admin_identity
from unspun.api.app import app
from unspun.api.events import get_db
from unspun.core import content_feed
from unspun.core.config import Settings, get_settings
from unspun.core.content import fingerprint
from unspun.core.hybrid_contracts import HybridRules, Signal
from unspun.core.hybrid_feed import page
from unspun.core.hybrid_ranking import Candidate, ordered, render_page, time_key
from unspun.core.hybrid_recall import attach_signals
from unspun.core.models import ContentDerivation, ContentMaterial
from unspun.core.reader import InterestTarget, Mutation, mutate
from unspun.core.sources import Source


@pytest.fixture
def hybrid(monkeypatch: pytest.MonkeyPatch, enabled_sources: None) -> None:
    monkeypatch.setattr(get_settings(), "r2_hybrid_enabled", True)
    monkeypatch.setattr("unspun.core.hybrid_feed.load_sources", content_feed.load_sources)


def feed(session: Session, **values: Any) -> dict[str, Any]:
    return page(
        session,
        sort=values.get("sort", "recommended"),
        cursor=values.get("cursor"),
        limit=values.get("limit", 20),
        now=values.get("now", NOW),
    )


def candidate(
    identity: str,
    *,
    topic: bool = False,
    score: float = 3,
    age: int = 1,
    source: str = "a",
    domain: str = "science",
) -> Candidate:
    return Candidate(
        "topic" if topic else "content",
        identity,
        fingerprint(identity),
        "Engineering fixture",
        (source,),
        (domain,),
        {
            "kind": "occurred" if topic else "original",
            "precision": "time",
            "at": (NOW - timedelta(days=age)).isoformat(),
            "basis": "Engineering fixture",
        },
        {"card": {"summary": "Engineering fixture"}, "url": "https://example.org/fixture"},
        {"score": score},
        lanes=("readable",),
    )


def signal(c: Candidate, **changes: Any) -> Signal:
    return Signal.model_validate(
        {
            "id": "engineering-attention",
            "type": c.type,
            "target_id": c.id,
            "target_version": c.version,
            "kind": "public_attention",
            "origin": "engineering_fixture",
            "observed_at": NOW - timedelta(hours=1),
            "expires_at": NOW + timedelta(hours=1),
            "reason": "Engineering fixture; not a real observation",
            "reviewer": "test-fixture",
            "evidence_url": "https://example.org/engineering-fixture",
            "metric": "interactions",
            "raw_value": 3,
            **changes,
        }
    )


def test_default_off() -> None:
    assert not Settings().r2_hybrid_enabled
    with Session() as session, pytest.raises(HTTPException) as error:
        feed(session)
    assert error.value.status_code == 404


def test_fusion_signals_are_separate_and_missing_is_explicit() -> None:
    a, b, c = candidate("1"), candidate("2"), candidate("3")
    b.signals["public_attention"] = signal(b)
    c.signals["important"] = signal(
        c,
        id="engineering-impact",
        kind="important",
        metric="public_impact",
        evidence=[
            {
                "article_id": 3,
                "material_id": 3,
                "paragraph": 0,
                "quote": "Fixture public harm",
                "voice": "reported",
            }
        ],
    )
    rows = ordered([a, b, c], "recommended", HybridRules(), content_feed.rules())
    assert [r.id for r, _ in rows] == ["3", "2", "1"]
    assert rows[0][1]["attention_boost"] == 0
    assert rows[-1][1]["missing_signals"] == ["important", "public_attention"]
    assert rows[-1][1]["important"] is None
    assert rows[-1][1]["public_attention"] is None
    # More channels and reading score never manufacture a public signal.
    a.sources = ("a", "b", "c", "d")
    a.reasons["score"] = 9
    parts = ordered([a], "recommended", HybridRules(), content_feed.rules())[0][1]
    assert parts["importance_boost"] == parts["attention_boost"] == 0


@pytest.mark.parametrize(
    "metric", ["source_count", "reprint_count", "reading_value", "public_impact"]
)
def test_public_attention_cannot_use_proxies(metric: str) -> None:
    with pytest.raises(ValidationError):
        signal(candidate("1"), metric=metric)


def test_runtime_registry_rejects_fixture_and_bad_target_evidence() -> None:
    c = candidate("1")
    with pytest.raises(ValidationError, match="engineering"):
        HybridRules(signals=(signal(c),))
    for values in ({"target_version": "0" * 64}, {"expires_at": NOW - timedelta(minutes=1)}):
        attach_signals(c, [signal(c, **values)], NOW, [])
        assert not c.signals
    important = signal(
        c,
        kind="important",
        metric="public_impact",
        evidence=[
            {
                "article_id": 1,
                "material_id": 2,
                "paragraph": 0,
                "quote": "absent fixture evidence",
                "voice": "reported",
            }
        ],
    )
    attach_signals(c, [important], NOW, [])
    assert not c.signals


@pytest.mark.parametrize("sort", ["recommended", "latest"])
def test_page_local_compression_preserves_unique_members_and_all_ids(sort: str) -> None:
    topic = replace(candidate("t", topic=True), duplicate_ids=("copy", "opinion", "experience"))
    copy = candidate("copy")
    opinion = replace(candidate("opinion"), protect=True)
    experience = replace(candidate("experience"), protect=True)
    report = candidate("report")
    rows = ordered(
        [topic, copy, opinion, experience, report], sort, HybridRules(), content_feed.rules()
    )
    output = render_page(rows)
    assert len(output) == 5
    by_id = {i["id"]: i for i in output}
    assert by_id["copy"]["presentation"] == "reference"
    assert "card" not in by_id["copy"]["content"]
    assert all(by_id[i]["presentation"] == "full" for i in ("opinion", "experience", "report"))
    assert render_page([(copy, {})])[0]["presentation"] == "full"
    other = replace(candidate("other", topic=True), duplicate_ids=("copy",))
    assert len(render_page([(topic, {}), (other, {}), (copy, {})])) == 3


def test_latest_ignores_score_and_diversity_keeps_source_sets() -> None:
    a = candidate("old", score=20, age=8)
    b = candidate("new", score=0, age=0)
    unknown = replace(candidate("unknown", score=100), time={"precision": "unknown"})
    rows = ordered([a, unknown, b], "latest", HybridRules(), content_feed.rules())
    assert [c.id for c, _ in rows] == ["new", "old", "unknown"]
    date_only = {"precision": "date", "on": "2026-10-23", "basis": "Fixture date"}
    assert time_key(date_only) == datetime(2026, 10, 22, 16, tzinfo=UTC)
    assert "at" not in date_only
    same = [candidate(str(i), score=3, source="a") for i in range(6)]
    other = candidate("other", score=2.9, source="b", domain="culture")
    rows = ordered(same + [other], "recommended", HybridRules(), content_feed.rules())
    assert rows[3][0].id == "other"
    assert any(parts["diversity"] < 0 for _, parts in rows)


def test_stable_pages_return_same_snapshot_without_writes(
    db_session: Session, hybrid: None
) -> None:
    for age in range(5):
        ready(db_session, age=age)
    first = feed(db_session, limit=2)
    second = feed(db_session, cursor=first["next_cursor"], limit=2, now=NOW + timedelta(minutes=1))
    replay = feed(db_session, cursor=first["next_cursor"], limit=2, now=NOW + timedelta(minutes=2))
    assert second == replay
    third = feed(db_session, cursor=second["next_cursor"], limit=2)
    assert third["next_cursor"] is None
    assert len({r["id"] for p in (first, second, third) for r in p["items"]}) == 5
    assert feed(db_session, limit=2) == first
    assert all(x["type"] == "content" and len(x["version"]) == 64 for x in first["items"])
    assert first["recall"]["topic_candidates"] == 0


@pytest.mark.parametrize(
    "mutation", ["new", "material", "metadata", "source", "interest", "feedback", "revoke"]
)
def test_dependency_changes_conflict(
    db_session: Session, hybrid: None, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    a, _ = ready(db_session), ready(db_session)
    if mutation == "revoke":
        mutate(
            db_session,
            Mutation(version=0, mutation_id=uuid4()),
            "interest",
            InterestTarget(kind="domain", value="science").model_dump(),
            {"active": True},
        )
    first = feed(db_session, limit=1)
    if mutation == "new":
        ready(db_session, age=0)
    elif mutation == "material":
        material = db_session.get(ContentMaterial, a.current_material_id)
        assert material
        material.paragraphs = [{"kind": "paragraph", "text": "Changed engineering material"}]
    elif mutation == "metadata":
        a.metadata_fingerprint = "changed"
    elif mutation == "source":
        monkeypatch.setattr("unspun.core.hybrid_feed.load_sources", lambda: list[Source]())
    elif mutation in {"interest", "revoke"}:
        mutate(
            db_session,
            Mutation(version=int(mutation == "revoke"), mutation_id=uuid4()),
            "interest",
            InterestTarget(kind="domain", value="science").model_dump(),
            None if mutation == "revoke" else {"active": True},
        )
    else:
        mutate(
            db_session,
            Mutation(version=0, mutation_id=uuid4()),
            "feedback",
            {"content_id": a.id},
            {"value": "interested"},
        )
    db_session.flush()
    with pytest.raises(HTTPException) as error:
        feed(db_session, cursor=first["next_cursor"], limit=1)
    assert error.value.status_code == 409


@pytest.mark.parametrize("change", ["expired", "sort", "limit", "garbage", "oversized"])
def test_cursor_contract(db_session: Session, hybrid: None, change: str) -> None:
    ready(db_session)
    ready(db_session)
    first = feed(db_session, limit=1)
    values: dict[str, Any] = {"cursor": first["next_cursor"], "limit": 1}
    if change == "expired":
        values["now"] = NOW + timedelta(minutes=16)
    if change == "sort":
        values["sort"] = "latest"
    if change == "limit":
        values["limit"] = 2
    if change == "garbage":
        values["cursor"] = "???"
    if change == "oversized":
        values["cursor"] = "a" * 2001
    with pytest.raises(HTTPException) as error:
        feed(db_session, **values)
    assert error.value.status_code == 400


def test_independent_lanes_recall_interest_and_signals_beyond_readable_bound(
    db_session: Session, hybrid: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    older = ready(db_session, age=9, domain="culture")
    newer = ready(db_session, age=0)
    item = next(i for i in feed(db_session)["items"] if i["id"] == str(older.id))
    probe = candidate(str(older.id))
    probe.version = item["version"]
    observation = signal(probe, origin="observed")
    policy = HybridRules(readable_limit=1, content_lane_limit=1, signals=(observation,))
    monkeypatch.setattr("unspun.core.hybrid_feed.hybrid_rules", lambda: policy)
    mutate(
        db_session,
        Mutation(version=0, mutation_id=uuid4()),
        "interest",
        InterestTarget(kind="domain", value="culture").model_dump(),
        {"active": True},
    )
    page_result = feed(db_session)
    assert {i["id"] for i in page_result["items"]} == {str(older.id), str(newer.id)}
    old = next(i for i in page_result["items"] if i["id"] == str(older.id))
    assert old["ranking"]["recall_lanes"] == ["interest", "public_attention"]
    assert old["ranking"]["public_attention"]["raw_value"] == 3


def test_reprint_and_processing_do_not_become_original_time(
    db_session: Session, hybrid: None
) -> None:
    reprint = ready(db_session, kind="reprint", age=0)
    original = ready(db_session, age=8)
    before = feed(db_session, sort="latest")
    assert [i["id"] for i in before["items"]] == [str(original.id), str(reprint.id)]
    assert before["items"][1]["time"]["precision"] == "unknown"
    for row in db_session.scalars(
        select(ContentDerivation).where(ContentDerivation.article_id == reprint.id)
    ):
        row.updated_at = NOW
    db_session.flush()
    assert [i["id"] for i in feed(db_session, sort="latest")["items"]] == [
        str(original.id),
        str(reprint.id),
    ]


@pytest.mark.anyio
async def test_api_is_opt_in_and_legacy_shape_is_unchanged(
    db_session: Session, enabled_sources: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready(db_session)

    def db() -> Generator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = db
    app.dependency_overrides[require_admin_identity] = lambda: "engineering-fixture"
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://test"
        ) as client:
            legacy = await client.get("/api/feed")
            assert legacy.status_code == 200 and legacy.json()["ranking_version"] == "r1-reader-v1"
            assert "type" not in legacy.json()["items"][0]
            assert (await client.get("/api/feed?mode=mixed")).status_code == 404
            monkeypatch.setattr(get_settings(), "r2_hybrid_enabled", True)
            monkeypatch.setattr("unspun.core.hybrid_feed.load_sources", content_feed.load_sources)
            mixed = await client.get("/api/feed?mode=mixed")
            assert mixed.status_code == 200 and mixed.json()["version"] == "r2-hybrid-v1"
            assert (await client.get("/api/feed?mode=bad")).status_code == 422
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(require_admin_identity, None)


@pytest.mark.parametrize("kind", ["source", "author", "term"])
def test_explicit_interests_recall_beyond_general_pool(
    db_session: Session, hybrid: None, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    from tests.test_content_feed import TITLE

    monkeypatch.setattr("tests.test_content_feed.TITLE", TITLE + " AI ")
    old = ready(db_session, source="zhihu-daily", age=9, author_id="author-old")
    monkeypatch.setattr("tests.test_content_feed.TITLE", TITLE + " aid ")
    recent = ready(db_session, age=0, author_id="author-new")
    target = (
        InterestTarget(kind="source", value="zhihu-daily")
        if kind == "source"
        else InterestTarget(
            kind="author", value="Synthetic", platform="synthetic-platform", author_id="author-old"
        )
        if kind == "author"
        else InterestTarget(kind="term", value="AI")
    )
    mutate(
        db_session,
        Mutation(version=0, mutation_id=uuid4()),
        "interest",
        target.model_dump(),
        {"active": True},
    )
    monkeypatch.setattr(
        "unspun.core.hybrid_feed.hybrid_rules",
        lambda: HybridRules(readable_limit=1, content_lane_limit=1),
    )
    result = feed(db_session)
    assert {i["id"] for i in result["items"]} == {str(old.id), str(recent.id)}
    old_out = next(i for i in result["items"] if i["id"] == str(old.id))
    assert old_out["ranking"]["recall_lanes"] == ["interest"]


def test_batched_feedback_preserves_latest_alias_and_revoke(
    db_session: Session, hybrid: None
) -> None:
    from unspun.core.hybrid_recall import feedback_rows
    from unspun.core.reader import effective_feedback
    from unspun.core.reader_models import ContentFeedback

    canonical = ready(db_session)
    alias = ready(db_session)
    alias.canonical_content_id = canonical.id
    db_session.add_all(
        [
            ContentFeedback(article_id=canonical.id, value="interested", version=1),
            ContentFeedback(article_id=alias.id, value="not_interested", version=2),
        ]
    )
    db_session.flush()
    query = feedback_rows()
    actual = {r[0]: r[1] for r in db_session.execute(select(query.c.root_id, query.c.value))}
    assert actual == {k: v.value for k, v in effective_feedback(db_session).items()}
    assert feed(db_session)["items"][0]["ranking"]["feedback_value"] == "not_interested"
    feedback = db_session.get(ContentFeedback, alias.id)
    assert feedback
    db_session.delete(feedback)
    db_session.flush()
    assert feed(db_session)["items"][0]["ranking"]["feedback_value"] == "interested"


def test_unique_relation_in_another_topic_prevents_compression() -> None:
    copy = candidate("copy")
    reprint_topic = replace(candidate("t1", topic=True), duplicate_ids=(copy.id,))
    explanation_topic = replace(candidate("t2", topic=True), unique_ids=(copy.id,))
    assert (
        render_page([(copy, {}), (reprint_topic, {}), (explanation_topic, {})])[0]["presentation"]
        == "full"
    )
