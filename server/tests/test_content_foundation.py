"""R1 contracts and ownership isolation, using only synthetic test material."""

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tests.reading_fixtures import approve
from tests.test_summarize_cluster import FakeLlm
from unspun.core.content import (
    ContentMetadata,
    ContentTime,
    derivation_fingerprint,
    fingerprint,
)
from unspun.core.models import (
    Article,
    ContentDerivation,
    ContentIdentity,
    ContentMaterial,
    ContentObservation,
    ContentUrl,
    Event,
)
from unspun.core.params import get_scoring_params
from unspun.core.reading import publication_counts
from unspun.evaluation.legacy.cluster import assign_article
from unspun.evaluation.legacy.score import pending_score_conditions, score_event
from unspun.evaluation.legacy.summarize import (
    abandoned_summary_conditions,
    embed_articles,
    pending_embedding_conditions,
    pending_summary_ids,
    summarize_article,
)
from unspun.evaluation.legacy.viewpoints import candidate_viewpoint_ids, refresh_event_viewpoint


def article(session: Session, key: str, track: str = "r1", **values: Any) -> Article:
    item = Article(
        source_id="synthetic",
        url=f"https://example.org/{key}",
        title=key,
        processing_track=track,
        **values,
    )
    session.add(item)
    session.flush()
    return item


def material(session: Session, item: Article) -> ContentMaterial:
    row = ContentMaterial(
        article_id=item.id,
        input_fingerprint=fingerprint([item.id, "input"]),
        text_fingerprint=fingerprint("synthetic observed material"),
        metadata_fingerprint=fingerprint({}),
        extractor_version="synthetic-v1",
        schema_version="r1-material-v1",
        scope="open_text_unit",
        access_status="ok",
        completeness="observed_unit",
        completeness_basis="synthetic text unit",
        source_url=item.url,
        retrieved_at=datetime.now(UTC),
        response_status=200,
        paragraphs=[{"kind": "paragraph", "text": "synthetic observed material"}],
        evidence={"fixture": True},
    )
    session.add(row)
    session.flush()
    return row


@pytest.mark.parametrize("form", ["article", "post", "question", "video", "audio"])
def test_independent_forms_do_not_need_an_event(db_session: Session, form: str) -> None:
    item = article(db_session, form, content_form=form)
    row = material(db_session, item)
    item.current_material_id = row.id
    db_session.flush()
    db_session.expire_all()
    assert item.event_id is None
    assert item.current_material_id == row.id
    assert item.content is None and item.summary_grounding is None
    assert item.r1_metadata is None


def test_existing_defaults_do_not_invent_r1_metadata(db_session: Session) -> None:
    item = Article(source_id="old", title="historical", url="https://example.org/old")
    db_session.add(item)
    db_session.flush()
    assert item.processing_track == "legacy" and item.content_form == "unknown"
    assert item.platform is None and item.publisher_name is None and item.r1_metadata is None
    assert ContentMetadata().authors == ()


def test_platform_identities_and_url_aliases_are_unique(db_session: Session) -> None:
    first, second = article(db_session, "first"), article(db_session, "second")
    db_session.add(ContentIdentity(article_id=first.id, namespace="platform", external_id="123"))
    db_session.add(
        ContentUrl(article_id=first.id, url="https://example.org/alias", relation="redirect")
    )
    db_session.flush()
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(
            ContentIdentity(article_id=second.id, namespace="platform", external_id="123")
        )
        db_session.flush()
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(
            ContentUrl(article_id=second.id, url="https://example.org/alias", relation="redirect")
        )
        db_session.flush()
    db_session.add(
        ContentIdentity(article_id=second.id, namespace="other-platform", external_id="123")
    )
    db_session.flush()


def test_multisource_observations_preserve_unknown_signals(db_session: Session) -> None:
    item = article(db_session, "observed")
    for source in ("route-a", "route-b"):
        db_session.add(
            ContentObservation(
                article_id=item.id,
                source_id=source,
                item_key="same-platform-id",
                discovered_url=item.url,
                observed_at=datetime.now(UTC),
                observation_fingerprint=fingerprint("same capture"),
                metadata_snapshot={},
            )
        )
    db_session.flush()
    rows = list(db_session.scalars(select(ContentObservation)))
    assert len(rows) == 2 and all(row.rank is None and row.signals is None for row in rows)
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(
            ContentObservation(
                article_id=item.id,
                source_id="route-a",
                item_key="same-platform-id",
                discovered_url=item.url,
                observed_at=datetime.now(UTC),
                observation_fingerprint=fingerprint("same capture"),
                metadata_snapshot={},
            )
        )
        db_session.flush()


def test_material_pointer_cannot_reference_another_content(db_session: Session) -> None:
    first, second = article(db_session, "material-a"), article(db_session, "material-b")
    row = material(db_session, first)
    with pytest.raises(IntegrityError), db_session.begin_nested():
        second.current_material_id = row.id
        db_session.flush()


@pytest.mark.parametrize("cross_owner", [False, True])
def test_ready_requires_own_material_and_actual_evidence(
    db_session: Session,
    cross_owner: bool,
) -> None:
    first, second = article(db_session, "derived-a"), article(db_session, "derived-b")
    row = material(db_session, first)
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(
            ContentDerivation(
                article_id=second.id if cross_owner else first.id,
                material_id=row.id,
                kind="card",
                status="ready",
                input_fingerprint=fingerprint("card"),
                metadata_fingerprint=fingerprint({}),
                contract_version="synthetic-v1",
                review_contract="synthetic-review-v1",
                payload={} if cross_owner else None,
                review_evidence={} if cross_owner else None,
            )
        )
        db_session.flush()


def test_time_precision_rejects_invented_midnight_and_naive_time() -> None:
    with pytest.raises(ValidationError):
        ContentTime(
            kind="editorial",
            precision="date",
            on="2026-10-16",  # type: ignore[arg-type]
            at=datetime(2026, 10, 16, tzinfo=UTC),
            basis="date only",
        )
    with pytest.raises(ValidationError):
        ContentTime(kind="original", precision="time", at=datetime(2026, 10, 16), basis="naive")
    assert ContentTime(kind="original", precision="unknown").at is None
    with pytest.raises(ValidationError):
        ContentMetadata.model_validate({"media_url": "javascript:alert(1)"})


def test_semantic_metadata_and_every_derivation_version_change_reuse_key() -> None:
    base: dict[str, Any] = {
        "metadata": {"publisher": "synthetic", "authors": [], "times": []},
        "material_fingerprint": "text-v1",
        "extractor_version": "extractor-v1",
        "scope": "preview",
        "contract": "card-v1",
        "model": "small-v1",
        "review_contract": "review-v1",
        "review_model": "reviewer-v1",
    }
    original = derivation_fingerprint(**base)
    for field in base:
        changed: dict[str, Any] = {
            **base,
            field: {"authors": ["different"]} if field == "metadata" else "changed",
        }
        assert derivation_fingerprint(**changed) != original
    assert fingerprint({"b": 2, "a": 1}) == fingerprint({"a": 1, "b": 2})


def test_r1_is_excluded_from_legacy_backlogs_even_with_legacy_approval(db_session: Session) -> None:
    pending = article(db_session, "r1-pending")
    abandoned = article(db_session, "r1-abandoned", summary_failures=3)
    ready = article(db_session, "r1-ready")
    approve(ready)
    legacy = article(db_session, "legacy-pending", track="legacy")
    db_session.flush()
    assert pending_summary_ids(db_session, 100) == [legacy.id]
    assert not list(db_session.scalars(select(Article.id).where(*pending_embedding_conditions())))
    assert not list(db_session.scalars(select(Article.id).where(*abandoned_summary_conditions())))
    assert sum(publication_counts(db_session).values()) == 1
    assert {pending.id, abandoned.id, ready.id}.isdisjoint(pending_summary_ids(db_session, 100))


def test_legacy_entrypoints_refuse_r1_before_calling_models(db_session: Session) -> None:
    item = article(db_session, "no-legacy-calls")
    event = Event(title="synthetic event", articles=[item])
    db_session.add(event)
    db_session.flush()
    calls = (
        lambda: summarize_article(db_session, FakeLlm(), item),
        lambda: embed_articles(db_session, FakeLlm(), [item]),
        lambda: assign_article(db_session, item, 0.72),
        lambda: score_event(db_session, FakeLlm(), event, get_scoring_params(), {}),
        lambda: refresh_event_viewpoint(
            db_session,
            FakeLlm(),
            event,
            get_scoring_params().viewpoints,
            {},
        ),
    )
    for call in calls:
        with pytest.raises(ValueError, match="R1 content"):
            call()
    assert event.id not in db_session.scalars(select(Event.id).where(*pending_score_conditions()))
    assert event.id not in candidate_viewpoint_ids(db_session, min_sources=1)
