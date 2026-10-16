"""Single-user CAS mutations; replays never resurrect revoked preferences."""

import unicodedata
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from unspun.core.content import fingerprint
from unspun.core.models import Article
from unspun.core.reader_models import ContentFeedback, ReaderChange, ReaderInterest, ReaderState
from unspun.core.sources import load_sources

DOMAIN_KEYS = {
    "world",
    "china",
    "economy",
    "technology",
    "science",
    "health",
    "society",
    "culture",
    "life",
    "environment",
}


class Mutation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: StrictInt = Field(ge=0, le=2147483646)
    mutation_id: UUID


class InterestTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["domain", "term", "source", "author"]
    value: str = Field(min_length=1, max_length=200)
    platform: str | None = Field(default=None, min_length=1, max_length=80)
    author_id: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def valid_target(self) -> "InterestTarget":
        if (
            "\x00" in self.value
            or (self.platform and not self.platform.strip())
            or (self.author_id and not self.author_id.strip())
        ):
            raise ValueError("interest resource contains an invalid blank or null value")
        if not self.value.strip():
            raise ValueError("interest target cannot be blank")
        if self.kind == "domain" and self.value not in DOMAIN_KEYS:
            raise ValueError("unknown domain")
        if self.kind == "author" and not self.platform:
            raise ValueError("author requires a platform")
        if self.kind != "author" and (self.platform or self.author_id):
            raise ValueError("platform fields require author kind")
        if self.kind == "term" and len(self.value.strip()) > 60:
            raise ValueError("interest term is too long")
        return self

    def normalized(self) -> dict[str, Any]:
        value = unicodedata.normalize("NFKC", self.value).strip()
        return {
            "kind": self.kind,
            "value": value.casefold() if self.kind != "author" else value,
            "platform": self.platform.strip().casefold() if self.platform else None,
            "author_id": self.author_id.strip() if self.author_id else None,
        }

    def key(self) -> str:
        data = self.normalized()
        if self.kind == "author" and self.author_id:
            data["value"] = None
        return self.kind + ":" + fingerprint(data)


def support(target: dict[str, Any]) -> dict[str, Any]:
    kind = target["kind"]
    if kind == "source":
        source = next((s for s in load_sources() if s.id == target["value"]), None)
        return {
            "matching": "existing_source_id" if source else "unknown_source",
            "collection": "enabled_r1_path"
            if source and source.r1 and source.r1.discovery
            else "declared_disabled"
            if source and source.r1
            else "not_connected",
            "dedicated_author_collection": False,
        }
    if kind == "author":
        return {
            "matching": "platform_id" if target.get("author_id") else "platform_byline_unverified",
            "collection": "author_subscription_not_connected",
            "dedicated_author_collection": False,
        }
    return {
        "matching": "existing_material_terms" if kind == "term" else "reviewed_content_categories",
        "collection": "uses_enabled_source_paths",
        "dedicated_author_collection": False,
    }


def snapshot(
    session: Session, *, replayed: bool = False, unchanged: bool = False
) -> dict[str, Any]:
    state = session.get(ReaderState, 1)
    interests = list(session.scalars(select(ReaderInterest).order_by(ReaderInterest.resource_key)))
    feedback = list(session.scalars(select(ContentFeedback).order_by(ContentFeedback.article_id)))
    return {
        "version": state.version if state else 0,
        "sort": state.sort if state else "recommended",
        "interests": [
            {
                "resource_key": i.resource_key,
                "label": i.label,
                "target": i.target,
                "support": support(i.target),
            }
            for i in interests
        ],
        "feedback": [
            {"content_id": f.article_id, "value": f.value, "version": f.version} for f in feedback
        ],
        "replayed": replayed,
        "unchanged": unchanged,
    }


def feedback_target(session: Session, article_id: int) -> int:
    seen: set[int] = set()
    while article_id not in seen and len(seen) < 64:
        seen.add(article_id)
        article = session.get(Article, article_id)
        if article is None or article.processing_track != "r1":
            raise HTTPException(404, "R1 content not found")
        if article.canonical_content_id is None:
            return article.id
        article_id = article.canonical_content_id
    raise HTTPException(409, "Content identity changed; reload before feedback")


def mutate(
    session: Session,
    body: Mutation,
    kind: str,
    target: dict[str, Any],
    value: dict[str, Any] | None,
) -> dict[str, Any]:
    mutation_id = str(body.mutation_id)
    fp = fingerprint(
        {"kind": kind, "target": target, "value": value, "expected_version": body.version}
    )
    session.execute(
        insert(ReaderState).values(id=1, version=0, sort="recommended").on_conflict_do_nothing()
    )
    state = session.scalar(
        select(ReaderState)
        .where(ReaderState.id == 1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert state
    receipt = session.scalar(select(ReaderChange).where(ReaderChange.mutation_id == mutation_id))
    if receipt:
        if receipt.fingerprint != fp:
            raise HTTPException(
                409, detail={"code": "mutation_id_reused", "current": snapshot(session)}
            )
        return snapshot(session, replayed=True)
    if state.version != body.version:
        raise HTTPException(
            409, detail={"code": "reader_version_conflict", "current": snapshot(session)}
        )
    before: dict[str, Any] | None = None
    changed = True
    if kind == "interest":
        parsed = InterestTarget.model_validate(target)
        key = parsed.key()
        existing = session.get(ReaderInterest, key)
        before = {"target": existing.target, "label": existing.label} if existing else None
        after: dict[str, Any] | None = (
            {"target": parsed.normalized(), "label": parsed.value.strip()} if value else None
        )
        if before == after:
            changed = False
        elif after:
            if existing:
                existing.target, existing.label = after["target"], after["label"]
            else:
                if (session.scalar(select(func.count()).select_from(ReaderInterest)) or 0) >= 100:
                    raise HTTPException(422, "At most 100 active interests are supported")
                session.add(
                    ReaderInterest(
                        resource_key=key,
                        kind=parsed.kind,
                        target=after["target"],
                        label=after["label"],
                    )
                )
        elif existing:
            session.delete(existing)
    elif kind == "feedback":
        article_id = feedback_target(session, int(target["content_id"]))
        existing = session.get(ContentFeedback, article_id)
        before = {"value": existing.value} if existing else None
        after = value
        if before == after:
            changed = False
        elif after:
            if existing:
                existing.value, existing.version, existing.updated_at = (
                    after["value"],
                    state.version + 1,
                    datetime.now(UTC),
                )
            else:
                session.add(
                    ContentFeedback(
                        article_id=article_id, value=after["value"], version=state.version + 1
                    )
                )
        elif existing:
            session.delete(existing)
    elif kind == "browse":
        before = {"sort": state.sort}
        after = value
        if before == after:
            changed = False
        elif after:
            state.sort = after["sort"]
    else:
        raise ValueError("unsupported reader mutation")
    if not changed:
        return snapshot(session, unchanged=True)
    state.version += 1
    state.last_mutation_id = mutation_id
    state.last_mutation_fingerprint = fp
    state.updated_at = datetime.now(UTC)
    session.add(
        ReaderChange(
            version=state.version,
            mutation_id=mutation_id,
            fingerprint=fp,
            kind=kind,
            target=target,
            value={"before": before, "after": after},
        )
    )
    session.flush()
    return snapshot(session)
