"""Bounded topic retrieval from current qualified material and versioned embeddings."""

import math
import re
from datetime import datetime
from typing import Any

from sqlalchemy import case, func, literal, or_, select
from sqlalchemy.orm import Session

from unspun.core.content import fingerprint
from unspun.core.content_reading import CardDraft, ContentInput, publication_at
from unspun.core.member_contracts import MemberDecision, member_contract
from unspun.core.member_evidence import validate_selection
from unspun.core.models import Article
from unspun.core.sources import Source
from unspun.core.topic_models import Topic, TopicMember
from unspun.core.topics import (
    canonical_content_id,
    member_input_snapshot,
    validate_member,
    validate_topic_evidence,
)

SCAN_TOPICS = 32
EMBED_TOPICS = 12
ANCHORS = 2
SCAN_ANCHORS = 32
CANDIDATES = 4


def current_input(
    session: Session, article_id: int, sources: list[Source], now: datetime
) -> dict[str, Any]:
    root = canonical_content_id(session, article_id)
    article = session.get(Article, root, populate_existing=True)
    if article is None or article.current_material_id is None:
        raise ValueError("member processing requires current material")
    return member_input_snapshot(session, root, article.current_material_id, sources, now)


def vector_input(snapshot: dict[str, Any]) -> dict[str, Any]:
    content = ContentInput.model_validate(snapshot["content"])
    # Bound provider bytes, while retaining the full input snapshot in the version key.
    text = (content.title + "\n" + content.model_text()).encode()[:24000].decode(errors="ignore")
    contract = member_contract()
    return {
        "snapshot": snapshot,
        "text": text,
        "version": contract["embedding"],
        "model": contract["embedding_model"],
        "dimensions": contract["dimensions"],
    }


def topic_candidate(
    session: Session,
    topic_id: str,
    sources: list[Source],
    now: datetime,
    *,
    trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    topic = session.get(Topic, topic_id, populate_existing=True)
    if topic is None or topic.status != "active":
        raise ValueError("candidate topic is unavailable")
    anchors: list[dict[str, Any]] = []
    checked: list[int] = []
    stale: list[int] = []
    for member in session.scalars(
        select(TopicMember)
        .where(TopicMember.topic_id == topic_id, TopicMember.active.is_(True))
        .order_by(TopicMember.article_id)
        .limit(SCAN_ANCHORS)
        .execution_options(populate_existing=True)
    ):
        checked.append(member.article_id)
        if not validate_member(session, member, sources, now).valid:
            stale.append(member.article_id)
            continue
        anchors.append(
            {
                "revision": member.revision,
                "relation": member.relation,
                "snapshot": current_input(session, member.article_id, sources, now),
            }
        )
        if len(anchors) == ANCHORS:
            break
    if trace is not None:
        trace.update(checked=checked, stale=stale, scan_cap=SCAN_ANCHORS)
    if not anchors:
        raise ValueError("candidate topic has no qualified anchor")
    return {
        "id": topic.id,
        "kind": topic.kind,
        "title": topic.title,
        "domains": topic.domains,
        "revision": topic.revision,
        "anchors": anchors,
    }


def _card(snapshot: dict[str, Any]) -> CardDraft:
    payload = snapshot["qualification"]["card"]["payload"]
    return CardDraft.model_validate(
        {k: v for k, v in payload.items() if k in CardDraft.model_fields}
    )


def subject_terms(snapshot: dict[str, Any]) -> tuple[str, ...]:
    """Use bounded original text even when the optional R1 card terms are empty."""
    content = ContentInput.model_validate(snapshot["content"])
    text = " ".join((*_card(snapshot).topics, content.title, content.text()[:2000])).lower()
    terms: dict[str, None] = {}
    stop = {"the", "and", "for", "with", "that", "this", "from", "after", "have", "has"}
    for word in re.findall(r"[a-z0-9]{3,}|[\u3400-\u9fff]+", text):
        parts = [word] if word.isascii() else [word[i : i + 2] for i in range(len(word) - 1)]
        for term in parts:
            if term not in stop:
                terms[term] = None
            if len(terms) >= 64:
                return tuple(terms)
    return tuple(terms)


def metadata_rank(query: dict[str, Any], candidate: dict[str, Any]) -> tuple[int, float, str]:
    subjects = set(subject_terms(query))
    at = publication_at(ContentInput.model_validate(query["content"]).metadata)
    overlap, distance = 0, math.inf
    for anchor in candidate["anchors"]:
        snapshot = anchor["snapshot"]
        overlap = max(overlap, len(subjects.intersection(subject_terms(snapshot))))
        other = publication_at(ContentInput.model_validate(snapshot["content"]).metadata)
        if at and other:
            distance = min(distance, abs((at - other).total_seconds()))
    return -overlap, distance, candidate["id"]


def _metadata_selection(
    query: dict[str, Any], candidates: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    ordered = sorted(candidates, key=lambda c: metadata_rank(query, c))
    # Keep two unknown-time and two background/older candidates under competition.
    # These are retrieval slots, never fabricated timestamps or semantic approvals.
    selected = ordered[: EMBED_TOPICS - 4]
    for group in (
        [
            c
            for c in ordered
            if any(
                publication_at(ContentInput.model_validate(a["snapshot"]["content"]).metadata)
                is None
                for a in c["anchors"]
            )
        ],
        [
            c
            for c in ordered
            if any(
                a["relation"] == "background"
                or (
                    (
                        at := publication_at(
                            ContentInput.model_validate(a["snapshot"]["content"]).metadata
                        )
                    )
                    is not None
                    and (
                        q := publication_at(ContentInput.model_validate(query["content"]).metadata)
                    )
                    is not None
                    and abs((q - at).days) > 30
                )
                for a in c["anchors"]
            )
        ],
    ):
        selected.extend([c for c in group if c not in selected][:2])
    selected.extend([c for c in ordered if c not in selected][: EMBED_TOPICS - len(selected)])
    return sorted(selected, key=lambda c: metadata_rank(query, c))


def recall_plan(
    session: Session,
    article_id: int,
    sources: list[Source],
    now: datetime,
    *,
    topic_ids: frozenset[str] | None = None,
) -> dict[str, Any]:
    query = current_input(session, article_id, sources, now)
    domain_filter = (
        Topic.status == "active",
        or_(*(Topic.domains.contains([d]) for d in _card(query).domains)),
        Topic.id.in_(topic_ids) if topic_ids is not None else literal(True),
    )
    existing = select(TopicMember.topic_id).where(
        TopicMember.article_id == query["content"]["article_id"],
        TopicMember.topic_id.in_(topic_ids) if topic_ids is not None else literal(True),
    )
    title_rank = sum(
        (
            case((func.strpos(func.lower(Topic.title), term) > 0, 1), else_=0)
            for term in subject_terms(query)
        ),
        literal(0),
    )
    identities = list(
        session.scalars(
            select(Topic.id)
            .where(*domain_filter, Topic.id.not_in(existing))
            .order_by(title_rank.desc(), Topic.id)
            .limit(SCAN_TOPICS)
        )
    )
    trace: dict[str, Any] = {
        "topic_scope": sorted(topic_ids) if topic_ids is not None else None,
        "domain_topics": session.scalar(
            select(func.count()).select_from(Topic).where(*domain_filter)
        ),
        "existing_member_topics": list(session.scalars(existing.order_by(TopicMember.topic_id))),
        "scanned_topic_ids": identities,
        "anchors": {},
        "unusable_topics": {},
    }
    selected: list[dict[str, Any]] = []
    for identity in identities:
        anchor_trace: dict[str, Any] = {}
        trace["anchors"][identity] = anchor_trace
        try:
            selected.append(topic_candidate(session, identity, sources, now, trace=anchor_trace))
        except ValueError as error:
            trace["unusable_topics"][identity] = str(error)
    topics = _metadata_selection(query, selected)
    trace.update(
        qualified_topic_ids=[c["id"] for c in selected],
        metadata_topic_ids=[c["id"] for c in topics],
    )
    return {"query": query, "topics": topics, "contract": member_contract(), "trace": trace}


def unit_vector(vector: list[float], dimensions: int) -> list[float]:
    if len(vector) != dimensions or any(not math.isfinite(v) for v in vector):
        raise ValueError("embedding dimensions or numeric values are invalid")
    norm = math.sqrt(sum(v * v for v in vector))
    if not math.isfinite(norm) or norm == 0:
        raise ValueError("embedding norm is invalid")
    return [v / norm for v in vector]


def select_candidates(
    plan: dict[str, Any], vectors: dict[str, list[float]]
) -> list[dict[str, Any]]:
    query_key = fingerprint(vector_input(plan["query"]))
    query = vectors[query_key]
    scored: list[tuple[float, str, dict[str, Any]]] = []
    for topic in plan["topics"]:
        keys = [fingerprint(vector_input(a["snapshot"])) for a in topic["anchors"]]
        score = max(sum(a * b for a, b in zip(query, vectors[key], strict=True)) for key in keys)
        scored.append((-score, topic["id"], {"topic": topic, "vectors": [query_key, *keys]}))
    scored.sort(key=lambda v: (v[0], v[1]))
    # The score is deliberately absent from semantic judgment and mutation payloads.
    return [v[2] for v in scored[:CANDIDATES]]


def validate_decision(session: Session, packet: dict[str, Any], decision: MemberDecision) -> None:
    validate_topic_evidence(session, validate_selection(packet, decision))
