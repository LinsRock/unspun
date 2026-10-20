"""Current reviewed R1 content, explainable ranking, and stable snapshot pagination."""

import base64
import re
import unicodedata
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import yaml
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy import DateTime, Select, and_, case, cast, func, or_, select
from sqlalchemy.dialects.postgresql import JSONPATH
from sqlalchemy.orm import Session

from unspun.core.config import get_settings
from unspun.core.content import ContentContract, fingerprint
from unspun.core.content_publication import Item, current_versions, qualified_items
from unspun.core.content_reading import (
    cheap_exclusion,
    current_value,
    publication_at,
)
from unspun.core.models import Article, ContentDerivation, ContentMaterial
from unspun.core.reader import effective_feedback
from unspun.core.reader_models import ReaderInterest, ReaderState
from unspun.core.sources import Source, load_sources


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


# Version the recall boundary independently of the unchanged scoring policy/API.
RETRIEVAL_VERSION = "r2-current-lanes-v1"


def publication_expression() -> Any:
    """Mirror publication_at; invalid external dates must not abort an entire query."""
    stamp = func.coalesce(
        func.jsonb_path_query_first(
            Article.r1_metadata, cast('$.times[*] ? (@.kind == "original")', JSONPATH)
        ),
        func.jsonb_path_query_first(
            Article.r1_metadata,
            cast('$.times[*] ? (@.kind == "editorial" || @.kind == "question_created")', JSONPATH),
        ),
    )
    at = func.jsonb_extract_path_text(stamp, "at")
    on = func.jsonb_extract_path_text(stamp, "on")
    return case(
        (func.pg_input_is_valid(at, "timestamp with time zone"), cast(at, DateTime(timezone=True))),
        (
            and_(at.is_(None), func.pg_input_is_valid(on, "date")),
            func.timezone("Asia/Shanghai", cast(on, DateTime())),
        ),
        else_=None,
    )


def candidate_versions(
    *, preview: bool, as_of: datetime, sources: list[Source], bound: int
) -> Select[Any]:
    at = publication_expression()
    genre = ContentDerivation.payload["genre"].astext
    evergreen = genre.in_(["knowledge", "review"])
    versions = (
        current_versions(preview=preview, as_of=as_of, sources=sources)
        .add_columns(Article.source_id, at.label("publication_at"), evergreen.label("evergreen"))
        .where(
            # These are the existing cheap_exclusion/current_value windows, not new scores.
            or_(
                at.is_(None),
                ContentMaterial.scope != "complete_brief",
                at >= as_of - timedelta(hours=48),
            ),
            or_(
                at.is_(None),
                Article.r1_metadata["genre"].astext.is_(None),
                Article.r1_metadata["genre"].astext.not_in(["old_report", "news"]),
                at >= as_of - timedelta(days=14),
            ),
            or_(
                at.is_(None),
                evergreen,
                and_(genre.in_(["analysis", "opinion"]), at >= as_of - timedelta(days=90)),
                and_(genre == "question", at >= as_of - timedelta(days=7)),
                and_(genre.in_(["news", "description"]), at >= as_of - timedelta(days=14)),
            ),
        )
        .subquery()
    )
    lane = case(
        (versions.c.publication_at.is_(None), "unknown"),
        (versions.c.evergreen, "evergreen"),
        else_="current",
    )
    rounds = select(
        versions,
        func.row_number()
        .over(
            partition_by=(versions.c.source_id, lane),
            order_by=(versions.c.publication_at.desc().nulls_last(), versions.c.article_id.desc()),
        )
        .label("position"),
    ).subquery()
    return (
        select(rounds)
        .order_by(
            rounds.c.position,
            rounds.c.publication_at.desc().nulls_last(),
            rounds.c.article_id.desc(),
        )
        .limit(bound)
    )


def reviewed(
    session: Session, *, preview: bool, as_of: datetime, sources: list[Source], policy: ReaderRules
) -> list[Item]:
    selected = candidate_versions(
        preview=preview, as_of=as_of, sources=sources, bound=policy.max_candidates
    ).subquery()
    items = qualified_items(session, selected)
    result: list[Item] = []
    for item in items:
        if cheap_exclusion(item.content, as_of):
            continue
        _, reason = current_value(item.content, item.card.genre, as_of)
        if reason == "outside_current_window" and item.card.genre not in {"knowledge", "review"}:
            continue
        result.append(item)
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
            "retrieval": RETRIEVAL_VERSION,
            "preview_sources": sorted({s for item in items for s in item.channels}),
            "preference_version": state.version if state else 0,
            "items": [
                [
                    i.article.id,
                    i.content.material_id,
                    i.content.metadata_fingerprint,
                    i.row.input_fingerprint,
                    i.row.updated_at.isoformat(),
                    [at.isoformat() for at in i.qualification_versions],
                    i.channels,
                ]
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
        [
            snapshot,
            sorted(
                (s.id, s.discovery_owner, s.r1.publish, s.r1.publish_scopes)
                for s in sources
                if s.r1
            ),
            preview,
        ]
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
