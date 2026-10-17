"""CAS, replay, revocation, target support and the unchanged legacy namespace."""

from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from unspun.core.models import Article, FeedPreference
from unspun.core.reader import InterestTarget, Mutation, mutate, snapshot
from unspun.core.reader_models import ContentFeedback, ReaderChange, ReaderState


def mutation(version: int) -> Mutation:
    return Mutation(version=version, mutation_id=uuid4())


def test_empty_reader_has_no_inferred_interests_and_get_is_read_only(db_session: Session) -> None:
    result = snapshot(db_session)
    assert result["version"] == 0 and result["sort"] == "recommended"
    assert result["interests"] == [] and result["feedback"] == []
    assert db_session.get(ReaderState, 1) is None
    assert db_session.scalar(select(func.count()).select_from(ReaderChange)) == 0


def test_interest_replay_after_revoke_never_resurrects_it(db_session: Session) -> None:
    target = InterestTarget(kind="term", value="AI").model_dump()
    add = mutation(0)
    first = mutate(db_session, add, "interest", target, {"active": True})
    assert first["version"] == 1 and len(first["interests"]) == 1
    again = mutate(db_session, add, "interest", target, {"active": True})
    assert again["version"] == 1 and again["replayed"] is True
    removed = mutate(db_session, mutation(1), "interest", target, None)
    assert removed["version"] == 2 and removed["interests"] == []
    replayed = mutate(db_session, add, "interest", target, {"active": True})
    assert replayed["version"] == 2 and replayed["interests"] == [] and replayed["replayed"]
    assert db_session.scalar(select(func.count()).select_from(ReaderChange)) == 2


def test_stale_device_and_reused_mutation_id_get_current_state(db_session: Session) -> None:
    body = mutation(0)
    mutate(db_session, body, "browse", {}, {"sort": "latest"})
    with pytest.raises(HTTPException) as error:
        mutate(db_session, mutation(0), "browse", {}, {"sort": "recommended"})
    assert error.value.status_code == 409
    assert isinstance(error.value.detail, dict)
    assert cast(dict[str, Any], error.value.detail)["current"]["version"] == 1
    with pytest.raises(HTTPException) as reused:
        mutate(db_session, body, "browse", {}, {"sort": "recommended"})
    assert isinstance(reused.value.detail, dict)
    assert cast(dict[str, Any], reused.value.detail)["code"] == "mutation_id_reused"
    assert db_session.get(FeedPreference, 1) is None


def test_feedback_changes_and_revokes_with_audited_versions(db_session: Session) -> None:
    article = Article(
        title="Synthetic",
        url="https://example.org/reader-feedback",
        source_id="synthetic",
        processing_track="r1",
    )
    db_session.add(article)
    db_session.flush()
    target = {"content_id": article.id}
    result = mutate(db_session, mutation(0), "feedback", target, {"value": "interested"})
    assert result["feedback"] == [{"content_id": article.id, "value": "interested", "version": 1}]
    mutate(db_session, mutation(1), "feedback", target, {"value": "not_interested"})
    mutate(db_session, mutation(2), "feedback", target, None)
    assert db_session.get(ContentFeedback, article.id) is None
    history = list(db_session.scalars(select(ReaderChange).order_by(ReaderChange.version)))
    assert all(r.value is not None for r in history)
    assert [(r.value or {})["after"] for r in history] == [
        {"value": "interested"},
        {"value": "not_interested"},
        None,
    ]
    with pytest.raises(HTTPException):
        mutate(
            db_session, mutation(3), "feedback", {"content_id": 987654321}, {"value": "interested"}
        )


def test_unknown_sources_and_authors_can_be_saved_without_claiming_collection(
    db_session: Session,
) -> None:
    target = InterestTarget(kind="source", value="not-connected-yet").model_dump()
    result = mutate(db_session, mutation(0), "interest", target, {"active": True})
    assert result["interests"][0]["support"]["collection"] == "not_connected"
    target = InterestTarget(
        kind="author", value="Unknown Author", platform="Unknown Platform"
    ).model_dump()
    result = mutate(db_session, mutation(1), "interest", target, {"active": True})
    author = next(i for i in result["interests"] if i["target"]["kind"] == "author")
    assert author["support"]["collection"] == "author_subscription_not_connected"
    assert author["support"]["matching"] == "platform_byline_unverified"


def test_semantically_identical_interest_save_does_not_bump_version(db_session: Session) -> None:
    target = InterestTarget(kind="domain", value="science").model_dump()
    mutate(db_session, mutation(0), "interest", target, {"active": True})
    result = mutate(db_session, mutation(1), "interest", target, {"active": True})
    assert result["version"] == 1 and result["unchanged"] is True


@pytest.mark.parametrize(
    "target",
    [
        {"kind": "domain", "value": "invented-domain"},
        {"kind": "term", "value": "   "},
        {"kind": "author", "value": "Name"},
        {"kind": "author", "value": "Name", "platform": "   "},
        {"kind": "source", "value": "source", "platform": "unexpected"},
    ],
)
def test_invalid_interest_resources_are_rejected(target: dict[str, str]) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        InterestTarget.model_validate(target)


def test_concurrent_devices_compare_against_current_locked_version(db_session: Session) -> None:
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from sqlalchemy import create_engine, delete

    from unspun.core.config import get_settings
    from unspun.core.reader_models import ReaderInterest

    engine = create_engine(get_settings().database_url)
    bodies = [mutation(0), mutation(0)]
    targets = [
        InterestTarget(kind="term", value=value)
        for value in ["synthetic-device-a", "synthetic-device-b"]
    ]
    barrier = threading.Barrier(2)
    with Session(engine) as session, session.begin():
        assert session.get(ReaderState, 1) is None
        session.add(ReaderState(id=1, version=0, sort="recommended"))

    def write(index: int) -> int:
        try:
            with Session(engine) as session, session.begin():
                cached = session.get(ReaderState, 1)
                assert cached and cached.version == 0
                barrier.wait(timeout=5)
                mutate(
                    session,
                    bodies[index],
                    "interest",
                    targets[index].model_dump(),
                    {"active": True},
                )
            return 200
        except HTTPException as error:
            return error.status_code

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(write, [0, 1]))
        assert sorted(statuses) == [200, 409]
        with Session(engine) as session:
            assert snapshot(session)["version"] == 1
            assert len(snapshot(session)["interests"]) == 1
    finally:
        with Session(engine) as session, session.begin():
            session.execute(
                delete(ReaderInterest).where(
                    ReaderInterest.resource_key.in_([t.key() for t in targets])
                )
            )
            session.execute(
                delete(ReaderChange).where(
                    ReaderChange.mutation_id.in_([str(b.mutation_id) for b in bodies])
                )
            )
            session.execute(
                delete(ReaderState).where(ReaderState.id == 1, ReaderState.version == 1)
            )
        engine.dispose()


def test_feedback_survives_later_canonical_merge_and_is_really_revocable(
    db_session: Session,
) -> None:
    root = Article(
        title="Root",
        url="https://example.org/feedback-root",
        source_id="synthetic",
        processing_track="r1",
    )
    alias = Article(
        title="Alias",
        url="https://example.org/feedback-alias",
        source_id="synthetic",
        processing_track="r1",
    )
    db_session.add_all([root, alias])
    db_session.flush()
    mutate(db_session, mutation(0), "feedback", {"content_id": alias.id}, {"value": "interested"})
    alias.canonical_content_id = root.id
    db_session.flush()
    state = snapshot(db_session)
    assert state["feedback"] == [{"content_id": root.id, "value": "interested", "version": 1}]
    removed = mutate(db_session, mutation(1), "feedback", {"content_id": alias.id}, None)
    assert removed["feedback"] == []
    assert db_session.get(ContentFeedback, alias.id) is None
    assert db_session.scalar(select(func.count()).select_from(ReaderChange)) == 2


def test_latest_feedback_wins_after_merge_and_update_keeps_one_active_record(
    db_session: Session,
) -> None:
    root = Article(
        title="Root",
        url="https://example.org/feedback-both-root",
        source_id="synthetic",
        processing_track="r1",
    )
    alias = Article(
        title="Alias",
        url="https://example.org/feedback-both-alias",
        source_id="synthetic",
        processing_track="r1",
    )
    db_session.add_all([root, alias])
    db_session.flush()
    mutate(
        db_session, mutation(0), "feedback", {"content_id": root.id}, {"value": "not_interested"}
    )
    mutate(db_session, mutation(1), "feedback", {"content_id": alias.id}, {"value": "interested"})
    alias.canonical_content_id = root.id
    db_session.flush()
    assert snapshot(db_session)["feedback"][0]["value"] == "interested"
    changed = mutate(
        db_session, mutation(2), "feedback", {"content_id": root.id}, {"value": "not_interested"}
    )
    assert changed["feedback"] == [{"content_id": root.id, "value": "not_interested", "version": 3}]
    assert db_session.scalar(select(func.count()).select_from(ContentFeedback)) == 1


def test_normalized_terms_remain_revocable_within_the_target_contract() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        InterestTarget(kind="term", value="\u337f" * 30)
    with pytest.raises(ValidationError):
        InterestTarget(kind="author", value="Name", platform="bad\x00platform")
