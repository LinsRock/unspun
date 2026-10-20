"""R1 grounded content contracts; no legacy Event or user rating is inferred."""

from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import Field, StrictBool, StrictInt

from unspun.core.content import ContentContract, ContentMetadata, MaterialScope, Paragraph
from unspun.core.grounding import (
    complete_fact_text,
    quote_in_source,
    supported_concepts,
    supported_qualifiers,
    supported_reported_time,
    supported_scope,
    supported_years,
    usable_evidence,
)
from unspun.core.reading import chinese_text

CARD_VERSION = "r1-card-v9"
GUIDE_VERSION = "r1-guide-v5"
REVIEW_VERSION = "r1-content-review-v2"
RULES_VERSION = "r1-content-rules-v1"
MODEL_INPUT_CHARS = 12000
DOMAINS = (
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
)
Genre = Literal["news", "analysis", "opinion", "knowledge", "review", "question", "description"]


class EvidenceClaim(ContentContract):
    text: str = Field(min_length=1, max_length=600)
    quote: str = Field(min_length=8, max_length=800)
    voice: Literal["reported", "author", "question", "description"]


class CardDraft(ContentContract):
    title_zh: str = Field(min_length=1, max_length=300)
    genre: Genre
    domains: tuple[str, ...] = Field(min_length=1, max_length=3)
    topics: tuple[str, ...] = Field(default=(), max_length=6)
    claims: tuple[EvidenceClaim, ...] = Field(max_length=3)
    reading_value: StrictInt = Field(ge=0, le=3)
    reading_reason: EvidenceClaim | None = None
    include: StrictBool
    reason: Literal[
        "supported_material", "insufficient_material", "stale_report", "no_reading_increment"
    ]


class GuideSection(ContentContract):
    heading: str = Field(min_length=1, max_length=60)
    claims: tuple[EvidenceClaim, ...] = Field(min_length=1, max_length=3)


class GuideDraft(ContentContract):
    available: StrictBool
    reason: Literal["supported_material", "insufficient_increment"]
    sections: tuple[GuideSection, ...] = Field(max_length=3)


class ContentInput(ContentContract):
    article_id: int
    material_id: int
    source_id: str
    title: str
    metadata: ContentMetadata
    scope: MaterialScope
    paragraphs: tuple[Paragraph, ...]
    material_fingerprint: str
    metadata_fingerprint: str
    extractor_version: str
    material_observed_at: datetime
    canonical_content_id: int | None = None

    def text(self) -> str:
        return "\n".join(unit.text for unit in self.paragraphs)

    def model_text(self) -> str:
        return self.text()[:MODEL_INPUT_CHARS]


def publication_at(metadata: ContentMetadata) -> datetime | None:
    # Original, editorial and question creation have supported meanings. Feed/modified/reprint and
    # observation times never manufacture a new first-publication timestamp.
    times = [
        value
        for value in metadata.times
        if value.kind in {"original", "editorial", "question_created"}
    ]
    original = next((value for value in times if value.kind == "original"), None)
    value = original or next(iter(times), None)
    if value is None:
        return None
    if value.at is not None:
        return value.at.astimezone(UTC)
    if value.on is not None:
        # An internal date boundary is for comparison only, never serialized as
        # a claimed midnight publication time in the API.
        from zoneinfo import ZoneInfo

        return datetime.combine(
            value.on, datetime.min.time(), ZoneInfo("Asia/Shanghai")
        ).astimezone(UTC)
    return None


def material_exclusion(content: ContentInput) -> str | None:
    if content.canonical_content_id is not None:
        return "canonical_duplicate"
    body = content.text().strip()
    if content.scope == "none" or not body or body == content.title.strip():
        return "insufficient_material"
    return None


def cheap_exclusion(content: ContentInput, now: datetime) -> str | None:
    excluded = material_exclusion(content)
    if excluded:
        return excluded
    at = publication_at(content.metadata)
    if content.scope == "complete_brief" and at and now - at > timedelta(hours=48):
        return "stale_brief"
    if content.metadata.genre in {"old_report", "news"} and at and now - at > timedelta(days=14):
        return "stale_report"
    return None


def current_value(content: ContentInput, genre: Genre, now: datetime) -> tuple[float, str]:
    at = publication_at(content.metadata)
    if at is None:
        return 0, "publication_unknown"
    age = max(timedelta(0), now - at)
    if genre in {"knowledge", "review"}:
        return 0.25, "evergreen_supported_material"
    days = 90 if genre in {"analysis", "opinion"} else 7 if genre == "question" else 14
    if age > timedelta(days=days):
        return 0, "outside_current_window"
    return max(0.1, 1 - age.total_seconds() / (days * 86400)), "supported_publication_window"


def claim_valid(claim: EvidenceClaim, source: str, scope: MaterialScope) -> bool:
    if len(claim.text) > 600 or not chinese_text(claim.text) or not complete_fact_text(claim.text):
        return False
    if scope == "question_background" and claim.voice != "question":
        return False
    if scope == "media_description" and claim.voice != "description":
        return False
    # A source frame does not preserve uncertainty inside the assertion.
    uncertainty = (
        "\u542c\u8bf4",
        "\u636e\u8bf4",
        "\u597d\u50cf",
        "\u4f3c\u4e4e",
        "\u770b\u8d77\u6765",
        "\u4eff\u4f5b",
    )
    if any(word in claim.quote for word in uncertainty) and not any(
        word in claim.text for word in uncertainty
    ):
        return False
    return (
        quote_in_source(claim.quote, source)
        and usable_evidence(claim.quote)
        and supported_years(claim.text, source)
        and supported_concepts(claim.text, claim.quote)
        and supported_qualifiers(claim.text, claim.quote)
        and supported_scope(claim.text, claim.quote)
        and supported_reported_time(claim.text, claim.quote)
    )


def card_valid(draft: CardDraft, content: ContentInput) -> bool:
    source = content.model_text()
    if not chinese_text(draft.title_zh) or any(domain not in DOMAINS for domain in draft.domains):
        return False
    if any(topic not in source for topic in draft.topics):
        return False
    claims = draft.claims + ((draft.reading_reason,) if draft.reading_reason else ())
    if not all(claim_valid(claim, source, content.scope) for claim in claims):
        return False
    if draft.genre in {"opinion", "review"} and any(
        claim.voice != "author" for claim in draft.claims
    ):
        return False
    return not draft.include or (
        bool(draft.claims)
        and draft.reading_value >= 1
        and draft.reading_reason is not None
        and draft.reading_reason in draft.claims
        and draft.reason == "supported_material"
    )


def guide_valid(draft: GuideDraft, content: ContentInput) -> bool:
    if draft.available and not draft.sections:
        return False
    return all(
        chinese_text(section.heading)
        and all(claim_valid(claim, content.model_text(), content.scope) for claim in section.claims)
        for section in draft.sections
    )


def declared_genre(metadata: ContentMetadata) -> Genre | None:
    value = (metadata.genre or "").casefold()
    if any(term in value for term in ("\u4e66\u8bc4", "\u5f71\u8bc4", "review")):
        return "review"
    if any(term in value for term in ("\u8bc4\u8bba", "\u89c2\u70b9", "opinion")):
        return "opinion"
    if any(term in value for term in ("\u5206\u6790", "\u89e3\u8bfb", "analysis")):
        return "analysis"
    if any(term in value for term in ("\u77e5\u8bc6", "knowledge")):
        return "knowledge"
    return None


def attributed_claim(claim: EvidenceClaim, content: ContentInput, genre: str) -> EvidenceClaim:
    """Attach the known source boundary; never add a factual assertion."""
    # For Chinese materials publish the reviewed verbatim passage itself.
    # Keep the model paraphrase in generation_output for audit. This prevents
    # an approved but over-specific paraphrase from adding facts to a card.
    if chinese_text(claim.quote):
        claim = claim.model_copy(update={"text": claim.quote})
    if content.scope == "media_description":
        return claim.model_copy(
            update={
                "voice": "description",
                "text": "\u7b80\u4ecb\u4e2d\u63d0\u5230\uff1a" + claim.text,
            }
        )
    if content.scope == "question_background":
        return claim.model_copy(
            update={
                "voice": "question",
                "text": "\u95ee\u9898\u80cc\u666f\u4e2d\u63d0\u5230\uff1a" + claim.text,
            }
        )
    prefixes = {
        "opinion": "\u6587\u4e2d\u89c2\u70b9\uff1a",
        "review": "\u4f5c\u8005\u8bc4\u4ef7\uff1a",
        "analysis": "\u6587\u4e2d\u5206\u6790\uff1a",
        "knowledge": "\u6587\u4e2d\u89e3\u91ca\uff1a",
    }
    if genre in prefixes:
        return claim.model_copy(update={"voice": "author", "text": prefixes[genre] + claim.text})
    return claim.model_copy(update={"text": "\u6587\u4e2d\u79f0\uff1a" + claim.text})
