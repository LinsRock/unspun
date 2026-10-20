"""R2-05 storage, ownership, concurrency, and dependency fences with mocked R1 processing."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from threading import Barrier
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tests.test_content_feed import NOW, TEXT, ready
from unspun.core.config import get_settings
from unspun.core.content import fingerprint
from unspun.core.content_publication import qualified_item
from unspun.core.models import (
    Article,
    ContentDerivation,
    ContentIdentity,
    ContentMaterial,
    ContentObservation,
    Event,
)
from unspun.core.reader import InterestTarget
from unspun.core.sources import Source, load_sources
from unspun.core.topic_contracts import (
    DefineTopic,
    DerivationContract,
    EvidenceRef,
    RecordUpdate,
    RemoveMember,
    RetractUpdate,
    SaveDerivation,
    SetMember,
    TopicClaim,
    TopicMutation,
    TopicTime,
)
from unspun.core.topic_models import Topic, TopicChange, TopicDerivation, TopicMember, TopicUpdate
from unspun.core.topics import (
    TopicConflict,
    canonical_content_id,
    derivation_input,
    mutate_topic,
    read_topic,
    validate_version,
)

CONTRACT = DerivationContract(version="synthetic-draft-v1", review_version="not-reviewed-v1")
DEFINITION = DefineTopic(kind="event", title="Synthetic topic", domains=("science",))


@pytest.fixture
def sources() -> list[Source]:
    source = next(s for s in load_sources() if s.id == "xinhua")
    assert source.r1
    return [
        source.model_copy(
            update={
                "discovery_owner": "r1",
                "legacy_enabled": False,
                "r1": source.r1.model_copy(update={"publish": True, "publish_scopes": None}),
            }
        )
    ]


def body(version: int, change: Any, mutation_id: UUID | None = None) -> TopicMutation:
    return TopicMutation(
        mutation_id=mutation_id or uuid4(),
        expected_revision=version,
        actor="synthetic-test",
        reason="Exercise retained revision",
        change=change,
    )


def write(session: Session, topic: UUID, change: Any, sources: list[Source]) -> TopicChange:
    row = session.get(Topic, str(topic))
    return mutate_topic(
        session, topic, body(row.revision if row else 0, change), sources=sources, now=NOW
    )


def ref(article: Article, **changes: Any) -> EvidenceRef:
    return EvidenceRef.model_validate(
        {
            "article_id": article.id,
            "material_id": article.current_material_id,
            "paragraph": 0,
            "quote": TEXT[:100],
            "voice": "reported",
            **changes,
        }
    )


def member(article: Article, **changes: Any) -> SetMember:
    return SetMember.model_validate(
        {
            "article_id": article.id,
            "material_id": article.current_material_id,
            "relation": "report",
            "basis": "Synthetic relationship evidence",
            "decision_version": "manual-test-v1",
            "evidence": [ref(article).model_dump()],
            **changes,
        }
    )


def setup(session: Session, sources: list[Source]) -> tuple[UUID, Article]:
    topic, article = uuid4(), ready(session)
    write(session, topic, DEFINITION, sources)
    write(session, topic, member(article), sources)
    return topic, article


def update(
    session: Session, topic: UUID, article: Article, sources: list[Source], **changes: Any
) -> TopicUpdate:
    command = RecordUpdate.model_validate(
        {
            "update_id": uuid4(),
            "summary": "Synthetic asserted development",
            "decision_version": "manual-test-v1",
            "evidence": [ref(article).model_dump()],
            **changes,
        }
    )
    receipt = write(session, topic, command, sources)
    row = session.get(TopicUpdate, (str(topic), str(command.update_id), receipt.revision))
    assert row
    return row


def derive(
    session: Session, topic: UUID, article: Article, sources: list[Source]
) -> TopicDerivation:
    token = derivation_input(session, topic, CONTRACT, kind="overview", sources=sources, now=NOW)
    change = SaveDerivation(
        kind="overview",
        contract=CONTRACT,
        input_fingerprint=token,
        claims=(TopicClaim(text="Synthetic draft claim", evidence=(ref(article),)),),
    )
    receipt = write(session, topic, change, sources)
    row = session.get(TopicDerivation, (str(topic), "overview", receipt.revision))
    assert row
    return row


def valid(session: Session, row: TopicUpdate | TopicDerivation, sources: list[Source]) -> bool:
    return validate_version(session, row, sources=sources, now=NOW, contract=CONTRACT).valid


def test_many_to_many_and_independent_reading_leave_old_resources_untouched(
    db_session: Session, sources: list[Source]
) -> None:
    old = Event(title="Historical event")
    db_session.add(old)
    db_session.flush()
    topic, first = setup(db_session, sources)
    second, other_topic = ready(db_session), uuid4()
    before = db_session.scalar(select(func.count()).select_from(ContentDerivation))
    write(db_session, other_topic, DEFINITION.model_copy(update={"kind": "issue"}), sources)
    write(db_session, other_topic, member(first, relation="background"), sources)
    write(db_session, topic, member(second, relation="opinion"), sources)
    assert len(list(db_session.scalars(select(TopicMember)))) == 3
    assert db_session.get(Event, old.id) is old
    assert first.event_id is None and second.event_id is None
    assert db_session.scalar(select(func.count()).select_from(ContentDerivation)) == before
    assert qualified_item(db_session, first.id, preview=False, as_of=NOW, sources=sources)
    assert InterestTarget(kind="term", value="Synthetic topic").key().startswith("term:")
    assert not str(topic).startswith("term:")


@pytest.mark.parametrize("relation", ["report", "background", "opinion", "explanation", "reprint"])
def test_relations_do_not_implicitly_create_progress(
    db_session: Session, sources: list[Source], relation: str
) -> None:
    topic, article = setup(db_session, sources)
    write(db_session, topic, member(article, relation=relation), sources)
    assert db_session.scalar(select(func.count()).select_from(TopicUpdate)) == 0


def test_idempotent_receipt_cas_and_replay_after_removal(
    db_session: Session, sources: list[Source]
) -> None:
    topic, article = setup(db_session, sources)
    request = body(2, member(article))
    receipt = mutate_topic(db_session, topic, request, sources=sources, now=NOW)
    write(db_session, topic, RemoveMember(article_id=article.id), sources)
    assert mutate_topic(db_session, topic, request, sources=sources, now=NOW) is receipt
    current = db_session.get(TopicMember, (str(topic), article.id))
    assert current and not current.active
    with pytest.raises(TopicConflict, match="revision"):
        mutate_topic(db_session, topic, body(2, member(article)), sources=sources, now=NOW)
    with pytest.raises(TopicConflict, match="reused"):
        mutate_topic(
            db_session,
            topic,
            body(2, RemoveMember(article_id=article.id), request.mutation_id),
            sources=sources,
            now=NOW,
        )
    assert db_session.get(Topic, str(topic)).revision == 4  # type: ignore[union-attr]
    history = list(
        db_session.scalars(
            select(TopicChange)
            .where(TopicChange.topic_id == str(topic))
            .order_by(TopicChange.revision)
        )
    )
    assert history[-1].before and history[-1].before["active"] is True
    assert history[-1].after["active"] is False


@pytest.mark.parametrize("error", ["owner", "quote", "paragraph", "material", "canonical"])
def test_wrong_material_and_evidence_are_rejected_without_history(
    db_session: Session, sources: list[Source], error: str
) -> None:
    topic, article = setup(db_session, sources)
    other = ready(db_session)
    citation = ref(article)
    command = member(article)
    if error == "owner":
        citation = ref(article, material_id=other.current_material_id)
    elif error == "quote":
        citation = ref(article, quote="This quote was never present")
    elif error == "paragraph":
        citation = ref(article, paragraph=999)
    elif error == "material":
        command = member(article, material_id=other.current_material_id)
    else:
        citation = ref(article, article_id=other.id)
    command = command.model_copy(update={"evidence": (citation,)})
    with pytest.raises(ValueError):
        write(db_session, topic, command, sources)
    assert db_session.get(Topic, str(topic)).revision == 2  # type: ignore[union-attr]
    stored = db_session.get(TopicMember, (str(topic), article.id))
    assert stored
    with pytest.raises(IntegrityError), db_session.begin_nested():
        stored.material_id = other.current_material_id  # type: ignore[assignment]
        db_session.flush()


def test_alias_roots_legacy_and_identity_cycles(db_session: Session, sources: list[Source]) -> None:
    topic, article = setup(db_session, sources)
    alias = Article(
        source_id="synthetic",
        title="alias",
        url="https://example.org/alias",
        processing_track="r1",
        canonical_content_id=article.id,
    )
    legacy = Article(source_id="synthetic", title="legacy", url="https://example.org/legacy")
    db_session.add_all([alias, legacy])
    db_session.flush()
    assert canonical_content_id(db_session, alias.id) == article.id
    write(db_session, topic, member(article, article_id=alias.id), sources)
    assert db_session.get(TopicMember, (str(topic), alias.id)) is None
    with pytest.raises(ValueError, match="R1"):
        canonical_content_id(db_session, legacy.id)
    article.canonical_content_id = alias.id
    db_session.flush()
    with pytest.raises(ValueError, match="cycle"):
        canonical_content_id(db_session, alias.id)


def test_update_revisions_retractions_and_unknown_time_are_retained(
    db_session: Session, sources: list[Source]
) -> None:
    topic, article = setup(db_session, sources)
    first = update(db_session, topic, article, sources)
    assert first.payload["occurred"] == {
        "precision": "unknown",
        "at": None,
        "on": None,
        "basis": None,
    }
    assert valid(db_session, first, sources)
    second = update(
        db_session,
        topic,
        article,
        sources,
        update_id=first.update_id,
        summary="Corrected assertion",
    )
    assert second.supersedes_revision == first.revision
    assert not valid(db_session, first, sources) and valid(db_session, second, sources)
    write(db_session, topic, RetractUpdate(update_id=UUID(first.update_id)), sources)
    view = read_topic(db_session, topic, sources=sources, now=NOW, contract=CONTRACT)
    assert [u["row"]["status"] for u in view["updates"]] == ["active", "active", "retracted"]
    assert all(not u["check"]["valid"] for u in view["updates"])
    assert view["updates"][-1]["row"]["payload"] == second.payload


@pytest.mark.parametrize(
    "data",
    [
        {"precision": "unknown", "on": "2026-10-20"},
        {"precision": "unknown", "basis": "guessed"},
        {"precision": "date", "on": "2026-10-20", "at": "2026-10-20T00:00:00Z", "basis": "text"},
        {"precision": "time", "at": "2026-10-20T10:00:00", "basis": "text"},
        {"precision": "time", "at": "2026-10-20T10:00:00Z"},
        {"precision": "date", "on": "2026-10-20"},
    ],
)
def test_unknown_and_date_times_cannot_invent_timestamp(data: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        TopicTime.model_validate(data)
    assert TopicTime(precision="date", on=date(2026, 10, 20), basis="cited date").at is None


def test_occurrence_and_reporting_time_need_their_own_evidence(
    db_session: Session, sources: list[Source]
) -> None:
    topic, article = setup(db_session, sources)
    with pytest.raises(ValueError, match="time basis"):
        update(
            db_session,
            topic,
            article,
            sources,
            occurred={
                "precision": "date",
                "on": "2026-10-20",
                "basis": "Absent temporal statement",
            },
        )
    row = update(
        db_session,
        topic,
        article,
        sources,
        reported={"precision": "date", "on": "2026-10-20", "basis": ref(article).quote[:8]},
    )
    assert row.payload["occurred"]["precision"] == "unknown"
    assert row.payload["reported"]["at"] is None


@pytest.mark.parametrize(
    "change",
    [
        "metadata",
        "material",
        "paragraph",
        "identity",
        "alias",
        "source",
        "scope",
        "source_version",
        "qualification",
    ],
)
def test_live_input_changes_invalidate_updates_and_drafts(
    db_session: Session, sources: list[Source], change: str
) -> None:
    topic, article = setup(db_session, sources)
    progress = update(db_session, topic, article, sources)
    derived = derive(db_session, topic, article, sources)
    assert valid(db_session, progress, sources) and valid(db_session, derived, sources)
    if change == "metadata":
        article.metadata_fingerprint = fingerprint("corrected")
    elif change == "material":
        article.current_material_id = None
    elif change == "paragraph":
        material = db_session.get(ContentMaterial, article.current_material_id)
        assert material
        material.paragraphs = [{"kind": "paragraph", "text": "Changed observed text"}]
    elif change == "identity":
        db_session.add(
            ContentIdentity(
                article_id=article.id, namespace="synthetic", external_id="new-identity"
            )
        )
    elif change == "alias":
        alias = Article(
            source_id="synthetic",
            title="alias",
            url="https://example.org/late-alias",
            processing_track="r1",
            canonical_content_id=article.id,
        )
        db_session.add(alias)
    elif change == "qualification":
        row = db_session.scalar(
            select(ContentDerivation).where(
                ContentDerivation.article_id == article.id, ContentDerivation.kind == "admission"
            )
        )
        assert row
        row.review_evidence = {"approved": False}
    else:
        source = sources[0]
        assert source.r1
        values: dict[str, Any] = (
            {"publish": False}
            if change == "source"
            else {"publish_scopes": ("media_description",)}
            if change == "scope"
            else {"version": "revised-boundary"}
        )
        sources = [source.model_copy(update={"r1": source.r1.model_copy(update=values)})]
    db_session.flush()
    assert not valid(db_session, progress, sources)
    assert not valid(db_session, derived, sources)


def test_member_boundary_is_narrow_for_updates_and_conservative_for_derivations(
    db_session: Session, sources: list[Source]
) -> None:
    topic, first = setup(db_session, sources)
    second = ready(db_session)
    write(db_session, topic, member(second), sources)
    progress = update(db_session, topic, first, sources)
    derived = derive(db_session, topic, first, sources)
    write(db_session, topic, member(second, relation="background"), sources)
    assert valid(db_session, progress, sources) and not valid(db_session, derived, sources)
    write(db_session, topic, RemoveMember(article_id=first.id), sources)
    assert not valid(db_session, progress, sources)
    write(db_session, topic, member(first), sources)
    assert not valid(db_session, progress, sources)
    assert qualified_item(db_session, first.id, preview=False, as_of=NOW, sources=sources)


def test_draft_revisions_contracts_late_results_and_read_only_validation(
    db_session: Session, sources: list[Source]
) -> None:
    topic, article = setup(db_session, sources)
    first = derive(db_session, topic, article, sources)
    second = derive(db_session, topic, article, sources)
    assert not valid(db_session, first, sources) and valid(db_session, second, sources)
    assert second.status == "draft" and second.supersedes_revision == first.revision
    assert not validate_version(
        db_session,
        second,
        sources=sources,
        now=NOW,
        contract=CONTRACT.model_copy(update={"version": "new-contract"}),
    ).valid
    stale_token = derivation_input(
        db_session, topic, CONTRACT, kind="overview", sources=sources, now=NOW
    )
    assert stale_token != derivation_input(
        db_session, topic, CONTRACT, kind="guide", sources=sources, now=NOW
    )
    write(db_session, topic, member(article, relation="background"), sources)
    command = SaveDerivation(
        kind="overview",
        contract=CONTRACT,
        input_fingerprint=stale_token,
        claims=(TopicClaim(text="Late result", evidence=(ref(article),)),),
    )
    with pytest.raises(TopicConflict, match="input changed"):
        write(db_session, topic, command, sources)
    db_session.flush()
    assert not db_session.new and not db_session.dirty
    view = read_topic(db_session, topic, sources=sources, now=NOW, contract=CONTRACT)
    assert len(view["derivations"]) == 2 and not db_session.new and not db_session.dirty


def test_repeated_observation_and_unrelated_source_do_not_invalidate(
    db_session: Session, sources: list[Source]
) -> None:
    topic, article = setup(db_session, sources)
    derived = derive(db_session, topic, article, sources)
    db_session.add(
        ContentObservation(
            article_id=article.id,
            source_id="unrelated-route",
            item_key="repeat",
            discovered_url=article.url,
            observed_at=NOW,
            observation_fingerprint="repeat",
            metadata_snapshot={},
        )
    )
    db_session.flush()
    unrelated = next(s for s in load_sources() if s.id == "bbc-world")
    assert valid(db_session, derived, [*sources, unrelated])


def test_topic_definition_changes_archive_and_input_revision(
    db_session: Session, sources: list[Source]
) -> None:
    topic, article = setup(db_session, sources)
    progress = update(db_session, topic, article, sources)
    derived = derive(db_session, topic, article, sources)
    write(db_session, topic, DEFINITION.model_copy(update={"title": "Corrected topic"}), sources)
    assert not valid(db_session, progress, sources) and not valid(db_session, derived, sources)
    write(db_session, topic, DEFINITION.model_copy(update={"status": "archived"}), sources)
    with pytest.raises(ValueError, match="archived"):
        derivation_input(db_session, topic, CONTRACT, kind="overview", sources=sources, now=NOW)


def test_cached_member_and_qualification_payload_are_refreshed(
    db_session: Session, sources: list[Source]
) -> None:
    topic, article = setup(db_session, sources)
    derived = derive(db_session, topic, article, sources)
    cached = db_session.get(TopicMember, (str(topic), article.id))
    assert cached and cached.relation == "report"
    db_session.connection().execute(
        text("UPDATE topic_members SET relation='background' WHERE topic_id=:topic"),
        {"topic": str(topic)},
    )
    assert cached.relation == "report"
    view = read_topic(db_session, topic, sources=sources, now=NOW, contract=CONTRACT)
    assert view["members"][0]["row"]["relation"] == "background"
    assert not valid(db_session, derived, sources)
    cached_card = db_session.scalar(
        select(ContentDerivation).where(
            ContentDerivation.article_id == article.id, ContentDerivation.kind == "card"
        )
    )
    assert cached_card
    db_session.connection().execute(
        text(
            "UPDATE content_derivations SET "
            "payload=payload || jsonb_build_object('title_zh','Unsupported draft') WHERE id=:id"
        ),
        {"id": cached_card.id},
    )
    with pytest.raises(ValueError, match="not currently qualified"):
        write(db_session, topic, member(article), sources)


def test_transaction_rollback_retains_previous_revision(
    db_session: Session, sources: list[Source]
) -> None:
    topic, article = setup(db_session, sources)
    with pytest.raises(RuntimeError, match="synthetic abort"), db_session.begin_nested():
        write(db_session, topic, RemoveMember(article_id=article.id), sources)
        raise RuntimeError("synthetic abort after all writes")
    current = db_session.get(Topic, str(topic))
    stored = db_session.get(TopicMember, (str(topic), article.id))
    assert current and current.revision == 2
    assert stored and stored.active
    assert db_session.scalar(select(func.count()).select_from(TopicChange)) == 2


@pytest.mark.parametrize("same_request", [True, False])
@pytest.mark.parametrize("existing", [True, False])
def test_real_concurrent_create_and_cas(
    same_request: bool, existing: bool, db_session: Session
) -> None:
    engine, topic = create_engine(get_settings().database_url), uuid4()
    barrier = Barrier(2)
    if existing:
        with Session(engine) as session, session.begin():
            mutate_topic(session, topic, body(0, DEFINITION), sources=[], now=NOW)
    first = body(int(existing), DEFINITION)
    requests = [first, first if same_request else body(int(existing), DEFINITION)]

    def attempt(index: int) -> str:
        try:
            with Session(engine) as session, session.begin():
                cached = session.get(Topic, str(topic))
                assert not existing or (cached and cached.revision == 1)
                barrier.wait(timeout=10)
                mutate_topic(session, topic, requests[index], sources=[], now=datetime.now(UTC))
            return "written"
        except TopicConflict:
            return "conflict"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, (0, 1)))
        assert sorted(results) == (
            ["written", "written"] if same_request else ["conflict", "written"]
        )
        with Session(engine) as session:
            stored = session.get(Topic, str(topic))
            assert stored and stored.revision == 1 + int(existing)
            assert session.scalar(
                select(func.count())
                .select_from(TopicChange)
                .where(TopicChange.topic_id == str(topic))
            ) == 1 + int(existing)
    finally:
        with Session(engine) as session, session.begin():
            session.execute(delete(TopicChange).where(TopicChange.topic_id == str(topic)))
            session.execute(delete(Topic).where(Topic.id == str(topic)))
        engine.dispose()
