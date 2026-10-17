"""Independent content ranking, exact feedback, material fencing and cursors."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_content_processing import TEXT, TITLE, FakeClient, approval, draft
from unspun.core.content import Author, ContentMetadata, ContentTime, fingerprint
from unspun.core.content_feed import page, term_matches
from unspun.core.models import Article, ContentDerivation, ContentMaterial
from unspun.core.reader import InterestTarget, Mutation, mutate
from unspun.core.sources import Source, load_sources
from unspun.pipeline.content_processing import apply_processing, load_content, organize

NOW = datetime.now(UTC) + timedelta(seconds=1)


@pytest.fixture
def enabled_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    sources: list[Source] = []
    for raw in load_sources():
        if raw.id in {"xinhua", "zhihu-daily"}:
            assert raw.r1
            sources.append(
                raw.model_copy(
                    update={
                        "discovery_owner": "r1",
                        "legacy_enabled": False,
                        "r1": raw.r1.model_copy(update={"publish": True, "paid": True}),
                    }
                )
            )
    monkeypatch.setattr("unspun.core.content_feed.load_sources", lambda: sources)
    monkeypatch.setattr("unspun.api.contents.load_sources", lambda: sources)


def ready(
    session: Session,
    *,
    source: str = "xinhua",
    domain: str = "science",
    age: int = 1,
    kind: str = "original",
    genre: str = "knowledge",
    author_id: str | None = None,
) -> Article:
    metadata = ContentMetadata.model_validate(
        {
            "form": "article",
            "genre": genre,
            "platform": "synthetic-platform",
            "authors": [
                Author(
                    name="Synthetic",
                    role="author",
                    platform="synthetic-platform",
                    platform_id=author_id,
                    basis="synthetic",
                ).model_dump()
            ],
            "times": [
                ContentTime.model_validate(
                    {
                        "kind": kind,
                        "precision": "time",
                        "at": NOW - timedelta(days=age),
                        "basis": "synthetic",
                    }
                ).model_dump(mode="json")
            ],
        }
    )
    article = Article(
        title=TITLE,
        url="https://example.org/content-feed/" + str(uuid4()),
        source_id=source,
        lang="zh",
        processing_track="r1",
        r1_metadata={"title": TITLE, **metadata.model_dump(mode="json")},
        metadata_fingerprint=fingerprint(metadata.model_dump(mode="json")),
    )
    session.add(article)
    session.flush()
    material = ContentMaterial(
        article_id=article.id,
        scope="open_text_unit",
        access_status="ok",
        completeness="observed_unit",
        completeness_basis="synthetic",
        source_url=article.url,
        retrieved_at=NOW - timedelta(seconds=2),
        input_fingerprint=fingerprint(article.url),
        metadata_fingerprint=article.metadata_fingerprint,
        extractor_version="synthetic-v1",
        schema_version="r1-material-v1",
        paragraphs=[{"kind": "paragraph", "text": TEXT}],
        evidence={},
    )
    session.add(material)
    session.flush()
    article.current_material_id = material.id
    session.flush()
    content = load_content(session, article.id)
    with Session() as disconnected:
        result = organize(
            disconnected,
            FakeClient(draft(domains=[domain], genre=genre)),
            FakeClient(approval()),
            content,
            now=NOW,
        )
    assert result.status == "ready"
    apply_processing(session, result)
    for row in session.scalars(
        select(ContentDerivation).where(ContentDerivation.article_id == article.id)
    ):
        row.updated_at = NOW - timedelta(seconds=1)
    session.flush()
    return article


def feed(session: Session, **values: Any) -> dict[str, Any]:
    return page(
        session,
        preview=False,
        sort=values.pop("sort", "recommended"),
        cursor=values.pop("cursor", None),
        limit=values.pop("limit", 20),
        now=values.pop("now", NOW),
    )


def test_no_preferences_and_domain_term_source_author_matches_are_explained(
    db_session: Session, enabled_sources: None
) -> None:
    science = ready(db_session, age=8, author_id="author-1")
    culture = ready(db_session, source="zhihu-daily", domain="culture")
    assert feed(db_session)["items"][0]["id"] == culture.id
    targets = [
        InterestTarget(kind="domain", value="science"),
        InterestTarget(kind="term", value=TEXT[:2]),
        InterestTarget(kind="source", value="xinhua"),
        InterestTarget(
            kind="author", value="Synthetic", platform="synthetic-platform", author_id="author-1"
        ),
    ]
    for version, target in enumerate(targets):
        mutate(
            db_session,
            Mutation(version=version, mutation_id=uuid4()),
            "interest",
            target.model_dump(),
            {"active": True},
        )
    items = feed(db_session)["items"]
    assert items[0]["id"] == science.id and items[0]["ranking"]["interest"] == 2
    assert len(items[0]["ranking"]["matched_interests"]) == 4
    assert [x["id"] for x in feed(db_session, sort="latest")["items"]] == [culture.id, science.id]


def test_feedback_revoke_changes_recommended_and_similar_penalty_is_bounded(
    db_session: Session, enabled_sources: None
) -> None:
    first = ready(db_session, author_id="same")
    second = ready(db_session, author_id="same")
    other = ready(db_session, author_id="different")
    mutate(
        db_session,
        Mutation(version=0, mutation_id=uuid4()),
        "feedback",
        {"content_id": first.id},
        {"value": "not_interested"},
    )
    scores = {x["id"]: x["ranking"] for x in feed(db_session)["items"]}
    assert scores[first.id]["feedback"] == -3
    assert (
        scores[second.id]["similar_feedback"] == -0.25 and scores[other.id]["similar_feedback"] == 0
    )
    mutate(
        db_session,
        Mutation(version=1, mutation_id=uuid4()),
        "feedback",
        {"content_id": first.id},
        None,
    )
    assert all(
        x["ranking"]["feedback"] == x["ranking"]["similar_feedback"] == 0
        for x in feed(db_session)["items"]
    )


def test_cursor_is_stable_then_conflicts_on_preferences_or_material_correction(
    db_session: Session, enabled_sources: None
) -> None:
    first = ready(db_session)
    ready(db_session)
    initial = feed(db_session, limit=1)
    next_page = feed(
        db_session, cursor=initial["next_cursor"], limit=1, now=NOW + timedelta(minutes=1)
    )
    assert initial["items"][0]["id"] != next_page["items"][0]["id"]
    mutate(db_session, Mutation(version=0, mutation_id=uuid4()), "browse", {}, {"sort": "latest"})
    with pytest.raises(HTTPException) as conflict:
        feed(db_session, cursor=initial["next_cursor"])
    assert conflict.value.status_code == 409
    token = feed(db_session, limit=1)["next_cursor"]
    first.metadata_fingerprint = "corrected"
    first.title = "Corrected title"
    db_session.flush()
    with pytest.raises(HTTPException) as corrected:
        feed(db_session, cursor=token)
    assert corrected.value.status_code == 409


@pytest.mark.parametrize("cursor", ["garbage", "a" * 2001])
def test_malformed_cursor_is_400(db_session: Session, enabled_sources: None, cursor: str) -> None:
    with pytest.raises(HTTPException) as error:
        feed(db_session, cursor=cursor)
    assert error.value.status_code == 400


def test_old_knowledge_remains_but_stale_reports_and_unknown_newness_are_not_promoted(
    db_session: Session, enabled_sources: None
) -> None:
    old = ready(db_session, age=1000)
    known = ready(db_session, age=3)
    unknown = ready(db_session, kind="feed", age=0)
    items = feed(db_session, sort="latest")["items"]
    assert [i["id"] for i in items] == [known.id, old.id, unknown.id]
    before = db_session.scalar(select(func.count()).select_from(ContentDerivation))
    assert feed(db_session)["items"]
    assert before == db_session.scalar(select(func.count()).select_from(ContentDerivation))


def test_old_contract_missing_admission_and_unreviewed_outputs_never_fall_back(
    db_session: Session, enabled_sources: None
) -> None:
    article = ready(db_session)
    row = db_session.scalar(
        select(ContentDerivation).where(
            ContentDerivation.article_id == article.id, ContentDerivation.kind == "admission"
        )
    )
    assert row
    row.review_evidence = {"approved": False}
    db_session.flush()
    assert feed(db_session)["items"] == []


def test_ascii_terms_have_word_boundaries() -> None:
    assert term_matches("AI", "An AI assistant")
    assert not term_matches("AI", "The source said hello")
