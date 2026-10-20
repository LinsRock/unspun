"""Bounded current recall and historical detail publication on a migrated isolated DB."""

from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event, insert, select, update
from sqlalchemy.orm import Session

from tests.test_content_feed import NOW, enabled_sources, feed, ready
from unspun.api.contents import find_item
from unspun.core.content import ContentMetadata
from unspun.core.content_feed import publication_expression, reviewed, rules
from unspun.core.content_publication import qualified_item
from unspun.core.content_reading import publication_at
from unspun.core.models import Article, ContentDerivation, ContentMaterial

__all__ = ["enabled_sources"]


def clone_ready(session: Session, count: int, **values: Any) -> list[int]:
    """Copy a mock-reviewed input; its fingerprint deliberately excludes object IDs."""
    seed = ready(session, **values)
    material = session.get(ContentMaterial, seed.current_material_id)
    assert material
    members = list(
        session.scalars(select(ContentDerivation).where(ContentDerivation.article_id == seed.id))
    )
    identities = (
        list(
            session.scalars(
                insert(Article).returning(Article.id),
                [
                    {
                        "source_id": seed.source_id,
                        "title": seed.title,
                        "url": f"https://example.org/r2/{uuid4()}",
                        "processing_track": "r1",
                        "r1_metadata": seed.r1_metadata,
                        "metadata_fingerprint": seed.metadata_fingerprint,
                    }
                    for _ in range(count - 1)
                ],
            )
        )
        if count > 1
        else []
    )
    material_ids = (
        list(
            session.scalars(
                insert(ContentMaterial).returning(ContentMaterial.id),
                [
                    {
                        "article_id": identity,
                        **{
                            name: getattr(material, name)
                            for name in (
                                "input_fingerprint",
                                "metadata_fingerprint",
                                "extractor_version",
                                "schema_version",
                                "scope",
                                "access_status",
                                "completeness",
                                "completeness_basis",
                                "source_url",
                                "retrieved_at",
                                "paragraphs",
                                "evidence",
                            )
                        },
                    }
                    for identity in identities
                ],
            )
        )
        if identities
        else []
    )
    if identities:
        session.execute(
            update(Article),
            [
                {"id": identity, "current_material_id": mid}
                for identity, mid in zip(identities, material_ids, strict=True)
            ],
        )
        session.execute(
            insert(ContentDerivation),
            [
                {
                    "article_id": identity,
                    "material_id": mid,
                    **{
                        name: getattr(member, name)
                        for name in (
                            "kind",
                            "status",
                            "reason",
                            "input_fingerprint",
                            "metadata_fingerprint",
                            "contract_version",
                            "generation_model",
                            "review_contract",
                            "review_model",
                            "payload",
                            "review_evidence",
                            "updated_at",
                        )
                    },
                }
                for identity, mid in zip(identities, material_ids, strict=True)
                for member in members
            ],
        )
    session.flush()
    return [seed.id, *identities]


def test_over_1000_current_candidates_are_bounded_fair_and_page_stably(
    db_session: Session, enabled_sources: None
) -> None:
    ids = clone_ready(db_session, 1005, genre="news")
    old_knowledge = ready(db_session, age=1000)
    unknown = ready(db_session, kind="feed", age=0)
    other_source = ready(db_session, source="zhihu-daily", age=2)
    items = reviewed(
        db_session, preview=False, as_of=NOW, sources=load_test_sources(), policy=rules()
    )
    selected = {i.article.id for i in items}
    assert len(selected) == 1000
    assert {ids[-1], old_knowledge.id, unknown.id, other_source.id} <= selected
    assert ids[0] not in selected
    # A candidate outside the bounded pool is still directly readable.
    assert find_item(db_session, ids[0], False)[0].article.id == ids[0]
    initial = feed(db_session, sort="latest", limit=50)
    seen = [i["id"] for i in initial["items"]]
    cursor = initial["next_cursor"]
    # A new result after as_of must not displace candidates while paging the old snapshot.
    later = ready(db_session)
    for row in db_session.scalars(
        select(ContentDerivation).where(ContentDerivation.article_id == later.id)
    ):
        row.updated_at = NOW + timedelta(seconds=1)
    db_session.flush()
    while cursor:
        result = feed(
            db_session, sort="latest", cursor=cursor, limit=50, now=NOW + timedelta(minutes=1)
        )
        seen.extend(i["id"] for i in result["items"])
        cursor = result["next_cursor"]
    assert len(seen) == len(set(seen)) == 1000
    assert set(seen) == selected
    assert later.id not in seen


def load_test_sources() -> list[Any]:
    # The existing fixture patches the module-level loader, including publication scopes.
    from unspun.core.content_feed import load_sources as configured

    return configured()


def test_historical_derivations_and_expired_news_do_not_consume_current_slots(
    db_session: Session, enabled_sources: None
) -> None:
    obsolete = clone_ready(db_session, 1005, genre="news")
    db_session.execute(
        update(ContentDerivation)
        .where(ContentDerivation.article_id.in_(obsolete))
        .values(contract_version="obsolete")
    )
    news = clone_ready(db_session, 1005, genre="news")
    background = ready(db_session, genre="analysis", age=100)
    knowledge = ready(db_session, genre="knowledge", age=1000)
    future = NOW + timedelta(days=20)
    result = feed(db_session, now=future)
    assert {i["id"] for i in result["items"]} == {knowledge.id}
    for identity in (news[0], background.id, knowledge.id):
        assert qualified_item(
            db_session, identity, preview=False, as_of=future, sources=load_test_sources()
        )
    assert (
        qualified_item(
            db_session, obsolete[-1], preview=False, as_of=future, sources=load_test_sources()
        )
        is None
    )


@pytest.mark.parametrize("kind", ["card", "features", "admission"])
@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "invalidated"),
        ("contract_version", "obsolete"),
        ("review_contract", "obsolete"),
        ("review_evidence", {"approved": "true"}),
        ("metadata_fingerprint", "obsolete"),
        ("input_fingerprint", "obsolete"),
        ("generation_model", "obsolete"),
    ],
)
def test_each_current_version_is_required_for_detail_and_feed(
    db_session: Session, enabled_sources: None, kind: str, field: str, value: Any
) -> None:
    article = ready(db_session)
    row = db_session.scalar(
        select(ContentDerivation).where(
            ContentDerivation.article_id == article.id, ContentDerivation.kind == kind
        )
    )
    assert row
    setattr(row, field, value)
    db_session.flush()
    assert feed(db_session)["items"] == []
    with pytest.raises(HTTPException) as missing:
        find_item(db_session, article.id, False)
    assert missing.value.status_code == 404


def test_material_revision_never_restores_previous_approved_text(
    db_session: Session, enabled_sources: None
) -> None:
    article = ready(db_session)
    material = db_session.get(ContentMaterial, article.current_material_id)
    assert material
    old = article.current_material_id
    replacement = ContentMaterial(
        article_id=article.id,
        **{
            name: getattr(material, name)
            for name in (
                "metadata_fingerprint",
                "extractor_version",
                "schema_version",
                "scope",
                "access_status",
                "completeness",
                "completeness_basis",
                "source_url",
                "retrieved_at",
                "paragraphs",
                "evidence",
            )
        },
        input_fingerprint="corrected-material",
    )
    db_session.add(replacement)
    db_session.flush()
    article.current_material_id = replacement.id
    db_session.flush()
    assert old != replacement.id and feed(db_session)["items"] == []
    with pytest.raises(HTTPException) as error:
        find_item(db_session, article.id, False)
    assert error.value.status_code == 404


def test_alias_chains_cycles_and_missing_canonical_target(
    db_session: Session, enabled_sources: None
) -> None:
    canonical = ready(db_session)
    first = Article(
        source_id="closed-alias",
        title="Alias",
        url=f"https://example.org/{uuid4()}",
        processing_track="r1",
        canonical_content_id=canonical.id,
    )
    db_session.add(first)
    db_session.flush()
    second = Article(
        source_id="closed-alias",
        title="Alias",
        url=f"https://example.org/{uuid4()}",
        processing_track="r1",
        canonical_content_id=first.id,
    )
    db_session.add(second)
    db_session.flush()
    item, alias = find_item(db_session, second.id, False)
    assert item.article.id == canonical.id and alias == second.id
    first.canonical_content_id = second.id
    db_session.flush()
    with pytest.raises(HTTPException) as cycle:
        find_item(db_session, second.id, False)
    assert cycle.value.status_code == 409
    first.canonical_content_id = canonical.id
    canonical.processing_track = "legacy"
    db_session.flush()
    with pytest.raises(HTTPException) as unavailable:
        find_item(db_session, second.id, False)
    assert unavailable.value.status_code == 404


@pytest.mark.parametrize(
    "change", ["scope", "owner", "publish", "admission", "material", "channels"]
)
def test_cursor_conflicts_on_current_publication_changes(
    db_session: Session, enabled_sources: None, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    first = ready(db_session)
    ready(db_session)
    token = feed(db_session, limit=1)["next_cursor"]
    sources = load_test_sources()
    source = sources[0]
    assert source.r1
    if change in {"scope", "owner", "publish"}:
        changes = (
            {"publish_scopes": ("open_text_unit",)} if change == "scope" else {"publish": False}
        )
        sources[0] = source.model_copy(
            update={"discovery_owner": "legacy"}
            if change == "owner"
            else {"r1": source.r1.model_copy(update=changes)}
        )
        monkeypatch.setattr("unspun.core.content_feed.load_sources", lambda: sources)
    elif change == "admission":
        row = db_session.scalar(
            select(ContentDerivation).where(
                ContentDerivation.article_id == first.id, ContentDerivation.kind == "admission"
            )
        )
        assert row
        row.updated_at = NOW + timedelta(seconds=1)
    elif change == "channels":
        from unspun.core.models import ContentObservation

        db_session.add(
            ContentObservation(
                article_id=first.id,
                source_id="new-channel",
                item_key="synthetic",
                discovered_url=first.url,
                observed_at=NOW,
                observation_fingerprint="synthetic",
                metadata_snapshot={},
            )
        )
    else:
        material = db_session.get(ContentMaterial, first.current_material_id)
        assert material
        material.metadata_fingerprint = "corrected-metadata"
    db_session.flush()
    with pytest.raises(HTTPException) as conflict:
        feed(db_session, cursor=token)
    assert conflict.value.status_code == 409


@pytest.mark.parametrize(
    "times",
    [
        [
            {
                "kind": "original",
                "precision": "time",
                "at": "2026-10-19T01:00:00+08:00",
                "basis": "test",
            }
        ],
        [{"kind": "editorial", "precision": "date", "on": "2026-10-19", "basis": "test"}],
        [
            {
                "kind": "question_created",
                "precision": "time",
                "at": "2026-10-18T03:00:00Z",
                "basis": "test",
            },
            {"kind": "original", "precision": "date", "on": "2024-01-01", "basis": "test"},
        ],
        [
            {"kind": "editorial", "precision": "date", "on": "2026-10-18", "basis": "test"},
            {"kind": "question_created", "precision": "date", "on": "2026-10-19", "basis": "test"},
        ],
        [{"kind": "feed", "precision": "time", "at": "2026-10-19T01:00:00Z", "basis": "test"}],
        [
            {"kind": "original", "precision": "unknown"},
            {"kind": "editorial", "precision": "date", "on": "2026-10-19", "basis": "test"},
        ],
        [],
    ],
)
def test_sql_publication_time_preserves_existing_time_semantics(
    db_session: Session, times: list[dict[str, Any]]
) -> None:
    article = Article(
        source_id="synthetic",
        title="Synthetic",
        url=f"https://example.org/{uuid4()}",
        processing_track="r1",
        r1_metadata={"times": times},
    )
    db_session.add(article)
    db_session.flush()
    actual = db_session.scalar(select(publication_expression()).where(Article.id == article.id))
    assert actual == publication_at(ContentMetadata.model_validate({"times": times}))


@pytest.mark.parametrize("date", ["2026-99-01", "not-a-date", "infinity", "2026-10-19T00:00:00"])
def test_bad_external_time_cannot_fail_other_readers(
    db_session: Session, enabled_sources: None, date: str
) -> None:
    article = ready(db_session)
    article.r1_metadata = {
        **(article.r1_metadata or {}),
        "times": [{"kind": "original", "precision": "time", "at": date, "basis": "test"}],
    }
    db_session.flush()
    assert feed(db_session)["items"] == []


def test_candidate_and_detail_queries_do_not_grow_per_item(
    db_session: Session, enabled_sources: None
) -> None:
    ids = clone_ready(db_session, 40)
    connection = db_session.connection()
    statements: list[str] = []

    def count(*args: Any) -> None:
        statements.append(str(args[2]))

    with Session(bind=connection) as fresh:
        event.listen(connection, "before_cursor_execute", count)
        try:
            assert (
                len(
                    reviewed(
                        fresh, preview=False, as_of=NOW, sources=load_test_sources(), policy=rules()
                    )
                )
                == 40
            )
            assert len(statements) == 2
            statements.clear()
            assert find_item(fresh, ids[0], False)[0].article.id == ids[0]
            assert len(statements) <= 3
        finally:
            event.remove(connection, "before_cursor_execute", count)


def test_alias_depth_guard_does_not_query_the_feed(
    db_session: Session, enabled_sources: None
) -> None:
    canonical = ready(db_session)
    previous = canonical
    for _ in range(65):
        alias = Article(
            source_id="synthetic",
            title="Alias",
            url=f"https://example.org/{uuid4()}",
            processing_track="r1",
            canonical_content_id=previous.id,
        )
        db_session.add(alias)
        db_session.flush()
        previous = alias
    with pytest.raises(HTTPException) as error:
        find_item(db_session, previous.id, False)
    assert error.value.status_code == 409
    with pytest.raises(HTTPException) as missing:
        find_item(db_session, -1, False)
    assert missing.value.status_code == 404


def test_old_news_details_keep_dates_and_create_no_work(
    db_session: Session, enabled_sources: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import datetime

    from starlette.requests import Request

    from unspun.api.contents import details
    from unspun.core.task_models import PipelineTask

    article = ready(db_session, genre="news")
    future = NOW + timedelta(days=20)

    class Clock(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            return future

    monkeypatch.setattr("unspun.api.contents.datetime", Clock)
    before = list(db_session.scalars(select(PipelineTask.id)))
    result = details(article.id, Request({"type": "http", "client": ("127.0.0.1", 1)}), db_session)
    assert result["id"] == article.id
    assert result["metadata"]["times"][0]["at"] == (NOW - timedelta(days=1)).isoformat().replace(
        "+00:00", "Z"
    )
    assert result["material"]["paragraphs"]
    assert list(db_session.scalars(select(PipelineTask.id))) == before
    assert feed(db_session, now=future)["items"] == []


@pytest.mark.parametrize("kind", ["card", "features", "admission"])
def test_unadmitted_payload_cannot_be_published_from_ready_rows(
    db_session: Session, enabled_sources: None, kind: str
) -> None:
    article = ready(db_session)
    row = db_session.scalar(
        select(ContentDerivation).where(
            ContentDerivation.article_id == article.id, ContentDerivation.kind == kind
        )
    )
    assert row
    row.payload = {**(row.payload or {}), "include": False}
    db_session.flush()
    assert feed(db_session)["items"] == []
    with pytest.raises(HTTPException) as missing:
        find_item(db_session, article.id, False)
    assert missing.value.status_code == 404
