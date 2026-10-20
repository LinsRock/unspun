"""Bounded topic retrieval from current qualified material and versioned embeddings."""

import math
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from unspun.core.content import fingerprint
from unspun.core.content_reading import CardDraft, ContentInput, publication_at
from unspun.core.member_contracts import MemberDecision, member_contract
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
    session: Session, topic_id: str, sources: list[Source], now: datetime
) -> dict[str, Any]:
    topic = session.get(Topic, topic_id, populate_existing=True)
    if topic is None or topic.status != "active":
        raise ValueError("candidate topic is unavailable")
    anchors: list[dict[str, Any]] = []
    for member in session.scalars(
        select(TopicMember)
        .where(TopicMember.topic_id == topic_id, TopicMember.active.is_(True))
        .order_by(TopicMember.article_id)
        .limit(ANCHORS)
        .execution_options(populate_existing=True)
    ):
        if not validate_member(session, member, sources, now).valid:
            raise ValueError("candidate anchor is stale")
        anchors.append(
            {
                "revision": member.revision,
                "relation": member.relation,
                "snapshot": current_input(session, member.article_id, sources, now),
            }
        )
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


def _metadata_rank(query: dict[str, Any], candidate: dict[str, Any]) -> tuple[int, float, str]:
    subjects = set(_card(query).topics)
    at = publication_at(ContentInput.model_validate(query["content"]).metadata)
    overlap, distance = 0, math.inf
    for anchor in candidate["anchors"]:
        snapshot = anchor["snapshot"]
        overlap = max(overlap, len(subjects.intersection(_card(snapshot).topics)))
        other = publication_at(ContentInput.model_validate(snapshot["content"]).metadata)
        if at and other:
            distance = min(distance, abs((at - other).total_seconds()))
    # Unknown and long-lived background remain eligible, after more specific metadata matches.
    return -overlap, distance, candidate["id"]


def recall_plan(
    session: Session, article_id: int, sources: list[Source], now: datetime
) -> dict[str, Any]:
    query = current_input(session, article_id, sources, now)
    selected: list[dict[str, Any]] = []
    for identity in session.scalars(
        select(Topic.id)
        .where(
            Topic.status == "active",
            or_(*(Topic.domains.contains([d]) for d in _card(query).domains)),
        )
        .order_by(Topic.id)
        .limit(SCAN_TOPICS)
    ):
        # Existing decisions, including removals, are never silently overwritten by inference.
        if session.get(TopicMember, (identity, query["content"]["article_id"])) is not None:
            continue
        try:
            selected.append(topic_candidate(session, identity, sources, now))
        except ValueError:
            continue
    selected.sort(key=lambda c: _metadata_rank(query, c))
    return {"query": query, "topics": selected[:EMBED_TOPICS], "contract": member_contract()}


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
    if not decision.associated:
        return
    topic = packet["candidate"]["topic"]
    if decision.classification in {"same_event", "same_issue"} and decision.classification != (
        "same_event" if topic["kind"] == "event" else "same_issue"
    ):
        raise ValueError("decision does not match the topic kind")
    query = packet["query"]["content"]
    own = (query["article_id"], query["material_id"])
    anchors = {
        (a["snapshot"]["content"]["article_id"], a["snapshot"]["content"]["material_id"])
        for a in topic["anchors"]
    }
    pairs = {(r.article_id, r.material_id) for r in decision.evidence}
    if own not in pairs or not pairs.intersection(anchors) or not pairs.issubset(anchors | {own}):
        raise ValueError("association requires content and candidate anchor evidence")
    validate_topic_evidence(session, decision.evidence)
