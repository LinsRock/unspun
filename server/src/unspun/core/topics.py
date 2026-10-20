"""Transactional topic storage and live dependency checks; no network, inference, or publication."""

from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import UUID

from sqlalchemy import inspect, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Mapper, Session

from unspun.core.content import ContentContract, fingerprint
from unspun.core.content_publication import qualified_item
from unspun.core.db import Base
from unspun.core.models import (
    Article,
    ContentDerivation,
    ContentIdentity,
    ContentMaterial,
    ContentUrl,
)
from unspun.core.sources import Source
from unspun.core.topic_contracts import (
    DefineTopic,
    DerivationContract,
    EvidenceRef,
    RecordUpdate,
    RemoveMember,
    RetractUpdate,
    SaveDerivation,
    SetMember,
    TopicMutation,
)
from unspun.core.topic_models import Topic, TopicChange, TopicDerivation, TopicMember, TopicUpdate


class TopicConflict(ValueError):
    """Reload current state or use a fresh mutation ID before retrying."""


class VersionCheck(ContentContract):
    valid: bool
    reasons: tuple[str, ...] = ()


def _dump(row: Base) -> dict[str, Any]:
    mapper = cast(Mapper[Any], inspect(type(row)))
    return {
        column.key: value.isoformat() if isinstance(value, datetime) else value
        for column in mapper.columns
        for value in [getattr(row, column.key)]
    }


def canonical_content_id(session: Session, article_id: int) -> int:
    seen: set[int] = set()
    while article_id not in seen and len(seen) < 64:
        seen.add(article_id)
        row = session.get(Article, article_id, populate_existing=True)
        if row is None or row.processing_track != "r1":
            raise ValueError("topic members require existing R1 content")
        if row.canonical_content_id is None:
            return row.id
        article_id = row.canonical_content_id
    raise ValueError("topic content identity contains a cycle or exceeds 64 hops")


def _identity_snapshot(session: Session, root: int) -> dict[str, Any]:
    group = select(Article.id).where(Article.id == root).cte(recursive=True)
    group = group.union(select(Article.id).join(group, Article.canonical_content_id == group.c.id))
    ids = select(group.c.id)
    return {
        "contents": [
            list(row)
            for row in session.execute(
                select(Article.id, Article.canonical_content_id, Article.source_id, Article.url)
                .where(Article.id.in_(ids))
                .order_by(Article.id)
            )
        ],
        "identities": [
            list(row)
            for row in session.execute(
                select(
                    ContentIdentity.article_id,
                    ContentIdentity.namespace,
                    ContentIdentity.external_id,
                )
                .where(ContentIdentity.article_id.in_(ids))
                .order_by(
                    ContentIdentity.article_id,
                    ContentIdentity.namespace,
                    ContentIdentity.external_id,
                )
            )
        ],
        "urls": [
            list(row)
            for row in session.execute(
                select(ContentUrl.article_id, ContentUrl.url, ContentUrl.relation)
                .where(ContentUrl.article_id.in_(ids))
                .order_by(ContentUrl.article_id, ContentUrl.url)
            )
        ],
    }


def member_input_snapshot(
    session: Session, article_id: int, material_id: int, sources: list[Source], now: datetime
) -> dict[str, Any]:
    if canonical_content_id(session, article_id) != article_id:
        raise ValueError("member identity changed")
    material = session.get(ContentMaterial, material_id, populate_existing=True)
    # A long-lived session may have cached an earlier ready result. SQL filters
    # alone do not refresh already loaded ORM payloads during qualification.
    list(
        session.scalars(
            select(ContentDerivation)
            .where(ContentDerivation.article_id == article_id)
            .execution_options(populate_existing=True)
        )
    )
    item = qualified_item(session, article_id, preview=False, as_of=now, sources=sources)
    if item is None or item.content.material_id != material_id:
        raise ValueError("member material is not currently qualified")
    assert material
    source = next(s for s in sources if s.id == item.article.source_id)
    assert source.r1
    return {
        "schema_version": "r2-topic-member-v1",
        "content": item.content.model_dump(mode="json"),
        "material": {
            key: _dump(material)[key]
            for key in (
                "input_fingerprint",
                "text_fingerprint",
                "metadata_fingerprint",
                "scope",
                "access_status",
                "completeness",
                "extractor_version",
                "schema_version",
                "source_url",
                "paragraphs",
            )
        },
        "identity": _identity_snapshot(session, article_id),
        "publication_boundary": {
            "source_id": source.id,
            "owner": source.discovery_owner,
            "publish": source.r1.publish,
            "publish_scopes": sorted(source.r1.publish_scopes)
            if source.r1.publish_scopes is not None
            else None,
            "material_scope": source.r1.material_scope,
            "origin_hosts": sorted(source.r1.origin_hosts),
            "version": source.r1.version,
        },
        "qualification": {
            "card": _dump(item.row),
            "features_at": item.qualification_versions[0].isoformat(),
            "admission_at": item.qualification_versions[1].isoformat(),
        },
    }


def validate_topic_evidence(session: Session, refs: tuple[EvidenceRef, ...]) -> None:
    for ref in refs:
        material = session.get(ContentMaterial, ref.material_id, populate_existing=True)
        if material is None or material.article_id != ref.article_id:
            raise ValueError("evidence material belongs to another content")
        if ref.paragraph >= len(material.paragraphs):
            raise ValueError("evidence paragraph is outside the material")
        if ref.quote not in material.paragraphs[ref.paragraph].get("text", ""):
            raise ValueError("evidence quote is absent from the referenced paragraph")
        voice = {"question_background": "question", "media_description": "description"}.get(
            material.scope
        )
        if voice and ref.voice != voice:
            raise ValueError("evidence voice exceeds the observed material scope")


def _definition(topic: Topic) -> dict[str, Any]:
    return {
        key: _dump(topic)[key]
        for key in ("id", "kind", "title", "domains", "status", "definition_revision")
    }


def validate_member(
    session: Session, member: TopicMember, sources: list[Source], now: datetime
) -> VersionCheck:
    if not member.active:
        return VersionCheck(valid=False, reasons=("member_removed",))
    try:
        current = member_input_snapshot(
            session, member.article_id, member.material_id, sources, now
        )
    except (ValueError, KeyError, TypeError):
        return VersionCheck(valid=False, reasons=("member_input_unavailable",))
    valid = fingerprint(current) == fingerprint(member.input_snapshot)
    return VersionCheck(valid=valid, reasons=() if valid else ("member_input_changed",))


def _references_snapshot(
    session: Session,
    topic: Topic,
    refs: tuple[EvidenceRef, ...],
    sources: list[Source],
    now: datetime,
) -> dict[str, Any]:
    validate_topic_evidence(session, refs)
    members: list[dict[str, Any]] = []
    for article_id, material_id in sorted({(r.article_id, r.material_id) for r in refs}):
        member = session.get(TopicMember, (topic.id, article_id), populate_existing=True)
        if (
            member is None
            or member.material_id != material_id
            or not validate_member(session, member, sources, now).valid
        ):
            raise ValueError("evidence requires a current active member and its pinned material")
        members.append(_dump(member))
    return {
        "schema_version": "r2-topic-references-v1",
        "definition": _definition(topic),
        "members": members,
    }


def _latest_update(session: Session, topic_id: str, update_id: str) -> TopicUpdate | None:
    return session.scalar(
        select(TopicUpdate)
        .where(TopicUpdate.topic_id == topic_id, TopicUpdate.update_id == update_id)
        .order_by(TopicUpdate.revision.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )


def _latest_derivation(session: Session, topic_id: str, kind: str) -> TopicDerivation | None:
    return session.scalar(
        select(TopicDerivation)
        .where(TopicDerivation.topic_id == topic_id, TopicDerivation.kind == kind)
        .order_by(TopicDerivation.revision.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )


def _update_check(
    session: Session, topic: Topic, row: TopicUpdate, sources: list[Source], now: datetime
) -> VersionCheck:
    latest = _latest_update(session, row.topic_id, row.update_id)
    if latest is None or latest.revision != row.revision:
        return VersionCheck(valid=False, reasons=("superseded",))
    if row.status == "retracted":
        return VersionCheck(valid=False, reasons=("retracted",))
    try:
        payload = RecordUpdate.model_validate(row.payload)
        current = _references_snapshot(session, topic, payload.evidence, sources, now)
        current["decision_version"] = payload.decision_version
    except (ValueError, KeyError, TypeError):
        return VersionCheck(valid=False, reasons=("update_input_unavailable",))
    valid = fingerprint(current) == row.input_fingerprint == fingerprint(row.input_snapshot)
    return VersionCheck(valid=valid, reasons=() if valid else ("update_input_changed",))


def _topic_snapshot(
    session: Session, topic: Topic, sources: list[Source], now: datetime
) -> dict[str, Any]:
    if topic.status != "active":
        raise ValueError("topic is archived")
    members = list(
        session.scalars(
            select(TopicMember)
            .where(TopicMember.topic_id == topic.id, TopicMember.active.is_(True))
            .order_by(TopicMember.article_id)
            .execution_options(populate_existing=True)
        )
    )
    if not members or any(not validate_member(session, m, sources, now).valid for m in members):
        raise ValueError("topic requires current qualified members")
    latest: dict[str, TopicUpdate] = {}
    for row in session.scalars(
        select(TopicUpdate)
        .where(TopicUpdate.topic_id == topic.id)
        .order_by(TopicUpdate.revision)
        .execution_options(populate_existing=True)
    ):
        latest[row.update_id] = row
    return {
        "schema_version": "r2-topic-input-v1",
        "definition": _definition(topic),
        "members": [_dump(m) for m in members],
        "updates": [
            {
                "row": _dump(latest[key]),
                "check": _update_check(session, topic, latest[key], sources, now).model_dump(
                    mode="json"
                ),
            }
            for key in sorted(latest)
        ],
    }


def derivation_input(
    session: Session,
    topic_id: UUID,
    contract: DerivationContract,
    *,
    kind: Literal["overview", "guide"],
    sources: list[Source],
    now: datetime,
) -> str:
    """Prepare a draft input token without mutating topic state or creating a task."""
    topic = session.get(Topic, str(topic_id), populate_existing=True)
    if topic is None:
        raise ValueError("topic does not exist")
    return fingerprint(
        {
            "kind": kind,
            "snapshot": _topic_snapshot(session, topic, sources, now),
            "contract": contract.model_dump(mode="json"),
        }
    )


def validate_version(
    session: Session,
    row: TopicUpdate | TopicDerivation,
    *,
    sources: list[Source],
    now: datetime,
    contract: DerivationContract | None = None,
) -> VersionCheck:
    """Validate a retained revision against live inputs; never trust a cached ready flag."""
    topic = session.get(Topic, row.topic_id, populate_existing=True)
    if topic is None or topic.status != "active":
        return VersionCheck(valid=False, reasons=("topic_unavailable",))
    if isinstance(row, TopicUpdate):
        return _update_check(session, topic, row, sources, now)
    latest = _latest_derivation(session, row.topic_id, row.kind)
    if latest is None or latest.revision != row.revision:
        return VersionCheck(valid=False, reasons=("superseded",))
    if contract is None or contract.model_dump(mode="json") != row.contract:
        return VersionCheck(valid=False, reasons=("derivation_contract_changed",))
    try:
        current = _topic_snapshot(session, topic, sources, now)
    except (ValueError, KeyError, TypeError):
        return VersionCheck(valid=False, reasons=("derivation_input_unavailable",))
    valid = fingerprint(current) == fingerprint(
        row.input_snapshot
    ) and row.input_fingerprint == fingerprint(
        {"kind": row.kind, "snapshot": current, "contract": row.contract}
    )
    return VersionCheck(valid=valid, reasons=() if valid else ("derivation_input_changed",))


def mutate_topic(
    session: Session,
    topic_id: UUID,
    mutation: TopicMutation,
    *,
    sources: list[Source],
    now: datetime,
) -> TopicChange:
    """Caller owns commit/rollback. Topic row lock serializes CAS and idempotent receipts."""
    key, change = str(topic_id), mutation.change
    request = mutation.model_dump(mode="json")
    fp = fingerprint(request)
    if isinstance(change, DefineTopic) and mutation.expected_revision == 0:
        session.execute(
            insert(Topic)
            .values(
                id=key,
                kind=change.kind,
                title=change.title,
                domains=list(change.domains),
                status=change.status,
                revision=0,
                definition_revision=0,
            )
            .on_conflict_do_nothing()
        )
    topic = session.scalar(
        select(Topic)
        .where(Topic.id == key)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if topic is None:
        raise ValueError("topic does not exist")
    receipt = session.scalar(
        select(TopicChange).where(
            TopicChange.topic_id == key, TopicChange.mutation_id == str(mutation.mutation_id)
        )
    )
    if receipt:
        if receipt.request_fingerprint != fp:
            raise TopicConflict("mutation ID was reused with a different request")
        return receipt
    if topic.revision != mutation.expected_revision:
        raise TopicConflict("topic revision changed")
    revision = topic.revision + 1
    before: dict[str, Any] | None = None
    if isinstance(change, DefineTopic):
        before = _definition(topic) if topic.revision else None
        topic.kind, topic.title = change.kind, change.title
        topic.domains, topic.status = list(change.domains), change.status
        topic.definition_revision = revision
        after = _definition(topic)
    elif isinstance(change, SetMember):
        root = canonical_content_id(session, change.article_id)
        snapshot = member_input_snapshot(session, root, change.material_id, sources, now)
        if any(
            (r.article_id, r.material_id) != (root, change.material_id) for r in change.evidence
        ):
            raise ValueError("member evidence must reference its canonical content and material")
        validate_topic_evidence(session, change.evidence)
        member = session.get(TopicMember, (key, root), populate_existing=True)
        before = _dump(member) if member else None
        if member is None:
            member = TopicMember(topic_id=key, article_id=root)
            session.add(member)
        member.material_id, member.revision, member.active = change.material_id, revision, True
        member.relation, member.basis, member.decision_version = (
            change.relation,
            change.basis,
            change.decision_version,
        )
        member.evidence, member.input_snapshot = (
            [r.model_dump(mode="json") for r in change.evidence],
            snapshot,
        )
        after = _dump(member)
    elif isinstance(change, RemoveMember):
        member = session.get(TopicMember, (key, change.article_id), populate_existing=True)
        if member is None:
            raise ValueError("member does not exist")
        before = _dump(member)
        member.active, member.revision = False, revision
        after = _dump(member)
    elif isinstance(change, RecordUpdate | RetractUpdate):
        previous = _latest_update(session, key, str(change.update_id))
        before = _dump(previous) if previous else None
        if isinstance(change, RecordUpdate):
            snapshot = _references_snapshot(session, topic, change.evidence, sources, now)
            snapshot["decision_version"] = change.decision_version
            for time in (change.occurred, change.reported):
                if time.basis and not any(time.basis in r.quote for r in change.evidence):
                    raise ValueError("topic time basis must occur in cited evidence")
            payload, status = change.model_dump(mode="json"), "active"
        else:
            if previous is None:
                raise ValueError("update does not exist")
            snapshot, payload, status = previous.input_snapshot, previous.payload, "retracted"
        update = TopicUpdate(
            topic_id=key,
            update_id=str(change.update_id),
            revision=revision,
            supersedes_revision=previous.revision if previous else None,
            status=status,
            payload=payload,
            input_snapshot=snapshot,
            input_fingerprint=fingerprint(snapshot),
        )
        session.add(update)
        after = {
            "update_id": update.update_id,
            "revision": revision,
            "status": status,
            "payload": payload,
            "input_snapshot": snapshot,
        }
    else:
        assert isinstance(change, SaveDerivation)
        snapshot = _topic_snapshot(session, topic, sources, now)
        actual = fingerprint(
            {
                "kind": change.kind,
                "snapshot": snapshot,
                "contract": change.contract.model_dump(mode="json"),
            }
        )
        if actual != change.input_fingerprint:
            raise TopicConflict("derivation input changed")
        refs = tuple(ref for claim in change.claims for ref in claim.evidence)
        _references_snapshot(session, topic, refs, sources, now)
        previous = _latest_derivation(session, key, change.kind)
        before = _dump(previous) if previous else None
        payload = {"claims": [c.model_dump(mode="json") for c in change.claims]}
        row = TopicDerivation(
            topic_id=key,
            kind=change.kind,
            revision=revision,
            supersedes_revision=previous.revision if previous else None,
            status="draft",
            input_fingerprint=actual,
            input_snapshot=snapshot,
            contract=change.contract.model_dump(mode="json"),
            payload=payload,
        )
        session.add(row)
        after = {
            "kind": change.kind,
            "revision": revision,
            "status": "draft",
            "input_fingerprint": actual,
            "input_snapshot": snapshot,
            "contract": row.contract,
            "payload": payload,
        }
    topic.revision, topic.updated_at = revision, now.astimezone(UTC)
    receipt = TopicChange(
        topic_id=key,
        revision=revision,
        mutation_id=str(mutation.mutation_id),
        request_fingerprint=fp,
        actor=mutation.actor,
        reason=mutation.reason,
        command=request["change"],
        before=before,
        after=after,
    )
    session.add(receipt)
    session.flush()
    return receipt


def read_topic(
    session: Session,
    topic_id: UUID,
    *,
    sources: list[Source],
    now: datetime,
    contract: DerivationContract,
) -> dict[str, Any]:
    """Internal retained view; structural validity never means public approval."""
    topic = session.get(Topic, str(topic_id), populate_existing=True)
    if topic is None:
        raise ValueError("topic does not exist")
    return {
        "topic": _dump(topic),
        "members": [
            {
                "row": _dump(m),
                "check": validate_member(session, m, sources, now).model_dump(mode="json"),
            }
            for m in session.scalars(
                select(TopicMember)
                .where(TopicMember.topic_id == topic.id)
                .order_by(TopicMember.article_id)
                .execution_options(populate_existing=True)
            )
        ],
        "updates": [
            {
                "row": _dump(row),
                "check": validate_version(session, row, sources=sources, now=now).model_dump(
                    mode="json"
                ),
            }
            for row in session.scalars(
                select(TopicUpdate)
                .where(TopicUpdate.topic_id == topic.id)
                .order_by(TopicUpdate.revision)
                .execution_options(populate_existing=True)
            )
        ],
        "derivations": [
            {
                "row": _dump(row),
                "check": validate_version(
                    session, row, sources=sources, now=now, contract=contract
                ).model_dump(mode="json"),
            }
            for row in session.scalars(
                select(TopicDerivation)
                .where(TopicDerivation.topic_id == topic.id)
                .order_by(TopicDerivation.revision)
                .execution_options(populate_existing=True)
            )
        ],
        "history": [
            _dump(row)
            for row in session.scalars(
                select(TopicChange)
                .where(TopicChange.topic_id == topic.id)
                .order_by(TopicChange.revision)
            )
        ],
    }
