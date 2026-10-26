"""Real SQL/API boundaries; protocol fixtures are not model quality evidence."""

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from tests.test_hybrid_topics import build, feed
from tests.test_topic_synthesis import REVIEWER, SynthesisDB, mock_draft
from tests.test_topic_synthesis import synthesis_db as synthesis_db
from tests.test_topics import member, write
from unspun.api.app import app
from unspun.api.events import get_db
from unspun.core.config import get_settings
from unspun.core.models import Article, ContentMaterial
from unspun.core.topic_contracts import RemoveMember
from unspun.core.topic_models import Topic
from unspun.core.topic_reading import topic_detail
from unspun.core.topic_synthesis import qualified_topic_text, synthesis_input

pytest_plugins = ["tests.test_billing"]


def read(db: SynthesisDB):
    with db.scope() as session:
        return topic_detail(session, db.topic, sources=db.sources, now=datetime.now(UTC))


def test_detail_is_id_based_without_feed_recall_or_write(
    synthesis_db: SynthesisDB, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = synthesis_db
    build(db, monkeypatch)
    monkeypatch.setattr(get_settings(), "r2_hybrid_enabled", False)
    before = len(db.billing.requests())
    with db.scope() as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        result = topic_detail(session, db.topic, sources=db.sources, now=datetime.now(UTC))
    assert result and result["id"] == str(db.topic)
    assert len(result["related"]) == 2
    assert result["overview"][0]["evidence"][0]["quote"]
    assert result["progress"][0]["occurred"]["precision"] == "unknown"
    assert result["progress"][0]["reported"]["precision"] == "unknown"
    assert result["progress"][0]["text"]
    assert result["context"][0]["classification"] == "background"
    assert result["context"][0]["limitations"]
    assert len(db.billing.requests()) == before


@pytest.mark.parametrize(
    "change", ["member", "remove", "material", "source", "publication", "mock"]
)
def test_detail_reuses_current_gate(
    synthesis_db: SynthesisDB, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    db = synthesis_db
    build(db, monkeypatch, mock=change == "mock")
    with db.scope() as session:
        article = session.get(Article, db.article)
        assert article
        if change == "member":
            write(session, db.topic, member(article, relation="opinion"), db.sources)
        elif change == "remove":
            write(session, db.topic, RemoveMember(article_id=db.article), db.sources)
        elif change == "material":
            material = session.get(ContentMaterial, article.current_material_id)
            assert material
            material.paragraphs = [{"kind": "paragraph", "text": "Updated material"}]
    if change == "source":
        source = db.sources[0]
        assert source.r1
        db.sources = [
            source.model_copy(update={"r1": source.r1.model_copy(update={"publish": False})})
        ]
    if change == "publication":
        monkeypatch.setattr(get_settings(), "r2_topic_publication_enabled", False)
    assert read(db) is None


@pytest.mark.anyio
async def test_topic_api_by_id_ignores_mixed_page_bounds(
    synthesis_db: SynthesisDB, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = synthesis_db
    build(db, monkeypatch)
    monkeypatch.setattr(get_settings(), "admin_local_preview", True)
    monkeypatch.setattr(get_settings(), "r2_hybrid_enabled", False)
    monkeypatch.setattr("unspun.api.topics.load_sources", lambda: db.sources)

    def database() -> Generator[Session]:
        with db.scope() as session:
            session.execute(text("SET TRANSACTION READ ONLY"))
            yield session

    monkeypatch.setitem(app.dependency_overrides, get_db, database)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(f"/api/topics/{db.topic}")
        assert response.status_code == 200
        assert response.json()["engineering_preview"] is False
        assert (await client.get(f"/api/topics/{uuid4()}")).status_code == 404
        assert (await client.get("/api/topics/not-a-uuid")).status_code == 422
        assert (await client.get("/api/reading-capabilities")).json()["home"] == "events"
        assert (await client.get("/api/feed?mode=mixed")).status_code == 404


@pytest.mark.anyio
async def test_topic_api_auth_before_disabled_or_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "admin_local_preview", False)
    monkeypatch.setattr(settings, "access_team_domain", "fixture.cloudflareaccess.com")
    monkeypatch.setattr(settings, "access_audience", "fixture")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get(f"/api/topics/{uuid4()}")).status_code == 401
        assert (await client.get("/api/reading-capabilities")).status_code == 401


def test_default_mock_stays_unpublishable(
    synthesis_db: SynthesisDB, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = synthesis_db
    build(db, monkeypatch, mock=True)
    with db.scope() as session:
        assert (
            qualified_topic_text(session, db.topic, sources=db.sources, now=datetime.now(UTC))
            is None
        )
        assert session.scalar(select(Article.id))


def test_expired_feed_progress_remains_readable_by_id_with_date_precision(
    synthesis_db: SynthesisDB, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = synthesis_db
    with db.scope() as session:
        topic = session.get(Topic, str(db.topic))
        assert topic
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
    on = (datetime.now(UTC) - timedelta(days=40)).date().isoformat()
    draft["contributions"][0]["occurred"] = {
        "precision": "date",
        "on": on,
        "basis": draft["contributions"][0]["evidence"][0]["quote"][:8],
    }
    db.draft_override = draft
    build(db, monkeypatch)
    assert not any(item["type"] == "topic" for item in feed(db)["items"])
    result = read(db)
    assert result and result["progress"][0]["occurred"]["on"] == on
    assert result["progress"][0]["occurred"]["at"] is None
    assert result["progress"][0]["reported"]["precision"] == "unknown"
