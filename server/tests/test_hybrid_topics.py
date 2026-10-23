"""Isolated simulated live-protocol records, never real/public model quality.

HTTP is always MockTransport. A live-shaped receipt exercises the *unchanged*
R2-07 verifier end to end; a normally labelled mock is rejected by that verifier.
No production eligibility bypass or mock option is installed in application code.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select

from tests.test_topic_synthesis import REVIEWER, SynthesisDB, mock_draft
from tests.test_topic_synthesis import synthesis_db as synthesis_db
from tests.test_topics import member, write
from unspun.core.billing_models import BilledRequest
from unspun.core.config import get_settings
from unspun.core.hybrid_feed import page
from unspun.core.models import Article, ContentMaterial
from unspun.core.topic_contracts import RemoveMember
from unspun.core.topic_models import Topic
from unspun.core.topic_synthesis import qualified_topic_text
from unspun.pipeline.topic_synthesis import enqueue_synthesis

pytest_plugins = ["tests.test_billing"]


def build(db: SynthesisDB, monkeypatch: pytest.MonkeyPatch, *, mock: bool = False) -> None:
    monkeypatch.setattr(get_settings(), "r2_topic_publication_enabled", True)
    monkeypatch.setattr(get_settings(), "r2_hybrid_enabled", True)
    monkeypatch.setattr("unspun.core.hybrid_feed.load_sources", lambda: db.sources)
    # All transport calls stay inside the isolated test fixture. This tests the
    # protocol shape, not provenance/semantic quality of a real provider response.
    db.mark_mock = mock
    with db.scope() as session:
        topic = session.get(Topic, str(db.topic))
        assert topic
        enqueue_synthesis(
            session,
            db.topic,
            topic.revision,
            REVIEWER,
            sources=db.sources,
            now=datetime.now(UTC),
            response_mode="mock" if mock else "live",
        )
    db.step("topic_synthesize")
    db.step("topic_synthesis_review")


def feed(db: SynthesisDB, **kwargs: Any) -> dict[str, Any]:
    with db.scope() as session:
        return page(
            session,
            sort=kwargs.get("sort", "latest"),
            cursor=kwargs.get("cursor"),
            limit=kwargs.get("limit", 20),
            now=datetime.now(UTC),
        )


def test_actual_r207_gate_accepts_simulated_live_shape_and_rejects_mock(
    synthesis_db: SynthesisDB, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = synthesis_db
    build(db, monkeypatch)
    result = feed(db)
    assert result["recall"]["topic_candidates"] == 1
    assert {i["type"] for i in result["items"]} == {"content", "topic"}
    topic = next(i for i in result["items"] if i["type"] == "topic")
    assert topic["time"]["precision"] == "unknown"
    assert topic["ranking"]["reading_value"] is None
    assert topic["ranking"]["important"] is None
    assert topic["ranking"]["feedback"] is None
    assert len(topic["topic"]["members"]) == 2
    # The production gate itself rejects an explicitly marked mock receipt.
    with db.scope() as session:
        request = session.scalar(select(BilledRequest).order_by(BilledRequest.started_at))
        assert request and request.response_payload
        request.response_payload = {**request.response_payload, "unspun_mock": True}
    result = feed(db)
    assert result["recall"]["topic_candidates"] == 0
    assert len(result["items"]) == 2


def test_labelled_mock_never_enters_mixed_api(
    synthesis_db: SynthesisDB, monkeypatch: pytest.MonkeyPatch
) -> None:
    build(synthesis_db, monkeypatch, mock=True)
    assert feed(synthesis_db)["recall"]["topic_candidates"] == 0


@pytest.mark.parametrize("mutation", ["member", "remove", "material", "source", "publication"])
def test_current_dependencies_invalidate_topic_and_cursor(
    synthesis_db: SynthesisDB, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    from fastapi import HTTPException

    db = synthesis_db
    build(db, monkeypatch)
    first = feed(db, limit=1)
    assert first["recall"]["topic_candidates"] == 1
    with db.scope() as session:
        article = session.get(Article, db.article)
        assert article
        if mutation == "remove":
            write(session, db.topic, RemoveMember(article_id=db.article), db.sources)
        elif mutation == "member":
            write(session, db.topic, member(article, relation="opinion"), db.sources)
        elif mutation == "material":
            material = session.get(ContentMaterial, article.current_material_id)
            assert material
            material.paragraphs = [{"kind": "paragraph", "text": "Changed fixture material"}]
    if mutation == "source":
        source = db.sources[0]
        assert source.r1
        db.sources = [
            source.model_copy(update={"r1": source.r1.model_copy(update={"publish": False})})
        ]
    if mutation == "publication":
        monkeypatch.setattr(get_settings(), "r2_topic_publication_enabled", False)
    with pytest.raises(HTTPException) as error:
        feed(db, cursor=first["next_cursor"], limit=1)
    assert error.value.status_code == 409
    assert feed(db)["recall"]["topic_candidates"] == 0
    if mutation not in {"source", "material"}:
        assert len(feed(db)["items"]) == 2


def test_topic_time_uses_progress_and_text_correction_does_not_refresh(
    synthesis_db: SynthesisDB, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = synthesis_db
    # Prepare the same deterministic response with a grounded engineering date.
    with db.scope() as session:
        topic = session.get(Topic, str(db.topic))
        assert topic
        from unspun.core.topic_synthesis import synthesis_input

        packet = synthesis_input(
            session,
            db.topic,
            topic.revision,
            REVIEWER,
            sources=db.sources,
            now=datetime.now(UTC),
            response_mode="live",
        )
    draft = mock_draft(
        {
            "members": [
                {"content": m["input_snapshot"]["content"]} for m in packet["snapshot"]["members"]
            ]
        }
    )
    contribution = draft["contributions"][0]
    contribution["occurred"] = {
        "precision": "time",
        "at": (datetime.now(UTC) - timedelta(days=2)).isoformat(),
        "basis": contribution["evidence"][0]["quote"][:8],
    }
    db.draft_override = draft
    build(db, monkeypatch)
    first = next(i for i in feed(db)["items"] if i["type"] == "topic")
    assert first["time"]["kind"] == "occurred"
    draft["contributions"][0] = {
        **contribution,
        "change": "correction",
        "text": contribution["text"] + " (fixture correction)",
    }
    with db.scope() as session:
        topic = session.get(Topic, str(db.topic))
        assert topic
        enqueue_synthesis(
            session,
            db.topic,
            topic.revision,
            REVIEWER,
            sources=db.sources,
            now=datetime.now(UTC),
            response_mode="live",
        )
    db.step("topic_synthesize")
    db.step("topic_synthesis_review")
    after = next(i for i in feed(db)["items"] if i["type"] == "topic")
    assert after["time"] == first["time"]
    assert after["version"] != first["version"]
    with db.scope() as session:
        assert qualified_topic_text(session, db.topic, sources=db.sources, now=datetime.now(UTC))
