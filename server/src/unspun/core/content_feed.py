"""Current reviewed R1 content, explainable ranking, and stable snapshot pagination."""

import base64
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import yaml
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from unspun.core.config import get_settings
from unspun.core.content import ContentContract, fingerprint
from unspun.core.content_reading import (
    CARD_VERSION,
    REVIEW_VERSION,
    CardDraft,
    ContentInput,
    card_valid,
    cheap_exclusion,
    current_value,
    publication_at,
)
from unspun.core.models import Article, ContentDerivation, ContentObservation
from unspun.core.reader import effective_feedback
from unspun.core.reader_models import ReaderInterest, ReaderState
from unspun.core.sources import Source, load_sources
from unspun.pipeline.content_processing import load_content, processing_fingerprint


class ReaderRules(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal["r1-reader-v1"]
    interest_weights: dict[str, float]
    interest_cap: float = Field(ge=0, le=2)
    positive_feedback: float = Field(ge=0, le=2)
    negative_feedback: float = Field(ge=-3, le=0)
    similar_negative_cap: float = Field(ge=0, le=0.25)
    source_window: int = Field(ge=1, le=10)
    source_soft_limit: int = Field(ge=1)
    source_penalty: float = Field(ge=0)
    domain_soft_limit: int = Field(ge=1)
    domain_penalty: float = Field(ge=0)
    cursor_minutes: int = Field(ge=1, le=15)
    max_candidates: int = Field(ge=1, le=1000)


def rules() -> ReaderRules:
    return ReaderRules.model_validate(
        yaml.safe_load((Path(get_settings().config_dir) / "r1-reader.yml").read_text())
    )


class Cursor(ContentContract):
    version: Literal["r1-cursor-v1"] = "r1-cursor-v1"
    sort: Literal["recommended", "latest"]
    as_of: datetime
    snapshot: str = Field(pattern=r"^[0-9a-f]{64}$")
    offset: StrictInt = Field(ge=1, le=1000)


def decode_cursor(value: str, sort: str, now: datetime, ttl: int) -> Cursor:
    try:
        if len(value) > 2000:
            raise ValueError("cursor too large")
        parsed = Cursor.model_validate_json(
            base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        )
        if (
            parsed.as_of.utcoffset() is None
            or parsed.sort != sort
            or not timedelta(0) <= now - parsed.as_of <= timedelta(minutes=ttl)
        ):
            raise ValueError("cursor is expired or has another order")
        return parsed
    except Exception as error:
        raise HTTPException(400, "Invalid or expired content cursor") from error


def encode_cursor(cursor: Cursor) -> str:
    return base64.urlsafe_b64encode(cursor.model_dump_json().encode()).decode().rstrip("=")


@dataclass
class Item:
    article: Article
    content: ContentInput
    row: ContentDerivation
    card: CardDraft
    channels: tuple[str, ...]


def reviewed(
    session: Session, *, preview: bool, as_of: datetime, sources: list[Source], policy: ReaderRules
) -> list[Item]:
    enabled = {
        s.id for s in sources if s.r1 and s.discovery_owner == "r1" and (s.r1.publish or preview)
    }
    rows = list(
        session.execute(
            select(Article, ContentDerivation)
            .join(ContentDerivation, ContentDerivation.article_id == Article.id)
            .where(
                Article.processing_track == "r1",
                Article.canonical_content_id.is_(None),
                Article.source_id.in_(enabled),
                ContentDerivation.kind == "card",
                ContentDerivation.status == "ready",
                ContentDerivation.contract_version == CARD_VERSION,
                ContentDerivation.review_contract == REVIEW_VERSION,
                ContentDerivation.updated_at <= as_of,
            )
            .order_by(Article.id)
            .limit(policy.max_candidates + 1)
        )
    )
    if len(rows) > policy.max_candidates:
        raise HTTPException(503, "Content candidate bound reached; narrow publication admission")
    identities = [a.id for a, _ in rows]
    members = (
        list(
            session.scalars(
                select(ContentDerivation).where(
                    ContentDerivation.article_id.in_(identities),
                    ContentDerivation.kind.in_(["features", "admission"]),
                )
            )
        )
        if identities
        else []
    )
    observations = (
        list(
            session.execute(
                select(
                    func.coalesce(Article.canonical_content_id, Article.id),
                    ContentObservation.source_id,
                )
                .join(ContentObservation, ContentObservation.article_id == Article.id)
                .where(func.coalesce(Article.canonical_content_id, Article.id).in_(identities))
                .distinct()
            )
        )
        if identities
        else []
    )
    result: list[Item] = []
    for article, row in rows:
        try:
            content = load_content(session, article.id)
            expected = processing_fingerprint(content, "card")
            if (
                row.input_fingerprint != expected
                or not (row.review_evidence or {}).get("approved")
                or row.material_id != article.current_material_id
            ):
                continue
            matching = [
                m
                for m in members
                if m.article_id == article.id
                and m.input_fingerprint == expected
                and m.material_id == article.current_material_id
                and m.status == "ready"
                and (m.review_evidence or {}).get("approved")
                and m.contract_version == CARD_VERSION
                and m.review_contract == REVIEW_VERSION
            ]
            if {m.kind for m in matching} != {"features", "admission"}:
                continue
            card = CardDraft.model_validate(
                {k: v for k, v in (row.payload or {}).items() if k in CardDraft.model_fields}
            )
            if not card.include or not card_valid(card, content) or cheap_exclusion(content, as_of):
                continue
            _, reason = current_value(content, card.genre, as_of)
            if reason == "outside_current_window" and card.genre not in {"knowledge", "review"}:
                continue
            channels = tuple(
                sorted(
                    {article.source_id} | {sid for aid, sid in observations if aid == article.id}
                )
            )
            result.append(Item(article, content, row, card, channels))
        except (ValueError, KeyError, TypeError):
            # A stale/poisoned payload is never a legacy fallback or a 500.
            continue
    return result


def normalized(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def term_matches(term: str, text: str) -> bool:
    term, text = normalized(term), normalized(text)
    if term.isascii() and any(c.isalnum() for c in term):
        return bool(re.search(r"(?<![a-z0-9_])" + re.escape(term) + r"(?![a-z0-9_])", text))
    return term in text


def author_ids(item: Item) -> set[tuple[str, str]]:
    return {
        (normalized(a.platform or item.content.metadata.platform or ""), a.platform_id)
        for a in item.content.metadata.authors
        if a.platform_id
    }


def matches(target: dict[str, Any], item: Item) -> bool:
    kind, value = target["kind"], target["value"]
    if kind == "domain":
        return value in item.card.domains
    if kind == "term":
        return term_matches(value, item.content.title + "\n" + item.content.text())
    if kind == "source":
        return value in item.channels
    if kind == "author":
        platform = normalized(target.get("platform") or "")
        if target.get("author_id"):
            return (platform, target["author_id"]) in author_ids(item)
        return any(
            normalized(a.name) == normalized(value)
            and normalized(a.platform or item.content.metadata.platform or "") == platform
            for a in item.content.metadata.authors
        )
    return False


def rank(
    session: Session, items: list[Item], as_of: datetime, sort: str, policy: ReaderRules
) -> tuple[list[tuple[Item, dict[str, Any]]], str]:
    state = session.get(ReaderState, 1)
    interests = list(session.scalars(select(ReaderInterest).order_by(ReaderInterest.resource_key)))
    feedback = {article_id: f.value for article_id, f in effective_feedback(session).items()}
    negative_authors: set[tuple[str, str]] = set()
    for item in items:
        if feedback.get(item.article.id) == "not_interested":
            negative_authors.update(author_ids(item))
    scored: list[tuple[Item, dict[str, Any]]] = []
    for item in items:
        matched = [i for i in interests if matches(i.target, item)]
        interest = min(
            policy.interest_cap, sum(policy.interest_weights.get(i.kind, 0) for i in matched)
        )
        explicit = feedback.get(item.article.id)
        feedback_value = (
            policy.positive_feedback
            if explicit == "interested"
            else policy.negative_feedback
            if explicit == "not_interested"
            else 0
        )
        similar = (
            -policy.similar_negative_cap
            if not explicit and author_ids(item) & negative_authors
            else 0
        )
        current, reason = current_value(item.content, item.card.genre, as_of)
        parts = {
            "reading_value": item.card.reading_value,
            "current_value": current,
            "current_reason": reason,
            "interest": interest,
            "feedback": feedback_value,
            "feedback_value": explicit,
            "similar_feedback": similar,
            "matched_interests": [i.resource_key for i in matched],
            "diversity": 0.0,
        }
        parts["score"] = item.card.reading_value + current + interest + feedback_value + similar
        scored.append((item, parts))
    snapshot = fingerprint(
        {
            "rules": policy.model_dump(),
            "preview_sources": sorted({s for item in items for s in item.channels}),
            "preference_version": state.version if state else 0,
            "items": [
                [i.article.id, i.row.input_fingerprint, i.row.updated_at.isoformat(), i.channels]
                for i in items
            ],
        }
    )
    floor = datetime.min.replace(tzinfo=UTC)
    if sort == "latest":
        scored.sort(
            key=lambda pair: (
                publication_at(pair[0].content.metadata) or floor,
                pair[0].article.id,
            ),
            reverse=True,
        )
        return scored, snapshot
    ordered: list[tuple[Item, dict[str, Any]]] = []
    while scored:
        history = ordered[-(policy.source_window - 1) :] if policy.source_window > 1 else []
        for item, parts in scored:
            source_count = sum(i.article.source_id == item.article.source_id for i, _ in history)
            domain_count = sum(i.card.domains[0] == item.card.domains[0] for i, _ in history)
            penalty = (policy.source_penalty if source_count >= policy.source_soft_limit else 0) + (
                policy.domain_penalty if domain_count >= policy.domain_soft_limit else 0
            )
            parts["diversity"] = -penalty
        best = max(
            range(len(scored)),
            key=lambda index: (
                scored[index][1]["score"] + scored[index][1]["diversity"],
                publication_at(scored[index][0].content.metadata) or floor,
                scored[index][0].article.id,
            ),
        )
        selected = scored.pop(best)
        selected[1]["total_score"] = selected[1]["score"] + selected[1]["diversity"]
        ordered.append(selected)
    return ordered, snapshot


def item_out(item: Item, explanation: dict[str, Any], sources: list[Source]) -> dict[str, Any]:
    names = {s.id: s.name for s in sources}
    return {
        "id": item.article.id,
        "title": item.card.title_zh,
        "original_title": item.content.title,
        "url": item.article.url,
        "source_id": item.article.source_id,
        "source_name": names.get(item.article.source_id, item.article.source_id),
        "channels": [{"id": s, "name": names.get(s, s)} for s in item.channels],
        "metadata": item.content.metadata.model_dump(mode="json"),
        "material_scope": item.content.scope,
        "material_id": item.content.material_id,
        "input_fingerprint": item.row.input_fingerprint,
        "card": item.row.payload,
        "feedback": explanation.get("feedback_value"),
        "ranking": explanation,
    }


def page(
    session: Session,
    *,
    preview: bool,
    sort: Literal["recommended", "latest"],
    cursor: str | None,
    limit: int,
    now: datetime,
) -> dict[str, Any]:
    policy = rules()
    token = decode_cursor(cursor, sort, now, policy.cursor_minutes) if cursor else None
    as_of = token.as_of if token else now
    sources = load_sources()
    items = reviewed(session, preview=preview, as_of=as_of, sources=sources, policy=policy)
    ordered, snapshot = rank(session, items, as_of, sort, policy)
    snapshot = fingerprint(
        [snapshot, sorted(s.id for s in sources if s.r1 and s.r1.publish), preview]
    )
    if token and token.snapshot != snapshot:
        raise HTTPException(409, "Content or reader preferences changed; reload the feed")
    offset = token.offset if token else 0
    if offset > len(ordered):
        raise HTTPException(400, "Cursor offset exceeds the content snapshot")
    end = offset + limit
    return {
        "items": [item_out(i, parts, sources) for i, parts in ordered[offset:end]],
        "next_cursor": encode_cursor(Cursor(sort=sort, as_of=as_of, snapshot=snapshot, offset=end))
        if end < len(ordered)
        else None,
        "sort": sort,
        "as_of": as_of,
        "ranking_version": policy.version,
        "preview": preview,
        "empty_reason": None if ordered else "no_reviewed_published_contents",
    }
