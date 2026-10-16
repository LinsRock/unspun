"""Versioned content metadata, material boundaries, and processing ownership."""

import hashlib
import json
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator
from sqlalchemy import ColumnElement, exists, select

from unspun.core.models import Article, Event

ContentForm = Literal["unknown", "article", "post", "question", "video", "audio"]
MaterialScope = Literal[
    "open_text_unit",
    "editorial_edition",
    "complete_brief",
    "preview",
    "question_background",
    "media_description",
    "feed_lead",
    "none",
]


class ContentContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Author(ContentContract):
    name: str = Field(min_length=1, max_length=300)
    role: Literal["author", "reporter", "editor", "compiler", "director", "account", "unknown"]
    platform: str | None = None
    platform_id: str | None = None
    basis: str = Field(min_length=1)


class ContentTime(ContentContract):
    kind: Literal["original", "feed", "modified", "reprint", "editorial", "question_created"]
    precision: Literal["time", "date", "unknown"]
    at: datetime | None = None
    on: date | None = None
    basis: str | None = None
    raw: str | None = None

    @model_validator(mode="after")
    def honest_precision(self) -> "ContentTime":
        if self.at is not None and self.at.utcoffset() is None:
            raise ValueError("content timestamps require a timezone")
        if self.precision == "time" and (self.at is None or not self.basis):
            raise ValueError("time precision requires a supported timestamp")
        if self.precision == "date" and (self.on is None or self.at is not None or not self.basis):
            raise ValueError("date precision must not invent a time")
        if self.precision == "unknown" and (self.at is not None or self.on is not None):
            raise ValueError("unknown precision must not contain an asserted time")
        return self


class ContentMetadata(ContentContract):
    schema_version: Literal["r1-metadata-v1"] = "r1-metadata-v1"
    form: ContentForm = "unknown"
    genre: str | None = None
    platform: str | None = None
    publisher: str | None = None
    authors: tuple[Author, ...] = ()
    times: tuple[ContentTime, ...] = ()
    original_url: HttpUrl | None = None
    media_url: HttpUrl | None = None
    duration_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    original_relation_basis: str | None = None


class Paragraph(ContentContract):
    kind: Literal["paragraph", "heading", "quote"] = "paragraph"
    text: str = Field(min_length=1, max_length=20000)


def fingerprint(value: Any) -> str:
    """Hash JSON semantics; callers provide all input/contract/model versions."""
    raw = json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def derivation_fingerprint(
    *,
    metadata: dict[str, Any],
    material_fingerprint: str,
    extractor_version: str,
    scope: MaterialScope,
    contract: str,
    model: str | None,
    review_contract: str,
    review_model: str | None,
) -> str:
    return fingerprint(
        {
            "metadata": metadata,
            "material": material_fingerprint,
            "extractor": extractor_version,
            "scope": scope,
            "contract": contract,
            "model": model,
            "review_contract": review_contract,
            "review_model": review_model,
        }
    )


def is_legacy(article: Article) -> bool:
    # SQLAlchemy constructor defaults apply only at INSERT; transient legacy
    # objects used by existing evaluators therefore have a None track.
    return article.processing_track in (None, "legacy")


def require_legacy(*articles: Article) -> None:
    if any(not is_legacy(article) for article in articles):
        raise ValueError("R1 content cannot enter the legacy processing pipeline")


def legacy_event_condition() -> ColumnElement[bool]:
    # Block mixed ownership rather than consuming an R1 member indirectly.
    return ~exists(
        select(Article.id)
        .where(
            Article.event_id == Event.id,
            Article.processing_track == "r1",
        )
        .correlate(Event)
    )
