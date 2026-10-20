"""Internal topic write contracts. These do not expose or approve public content."""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from unspun.core.content import ContentContract
from unspun.core.content_reading import DOMAINS

Nonblank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class EvidenceRef(ContentContract):
    article_id: int = Field(gt=0)
    material_id: int = Field(gt=0)
    paragraph: int = Field(ge=0)
    quote: str = Field(min_length=8, max_length=8000)
    voice: Literal["reported", "author", "question", "description"]


class TopicTime(ContentContract):
    precision: Literal["time", "date", "unknown"] = "unknown"
    at: datetime | None = None
    on: date | None = None
    basis: Nonblank | None = None

    @model_validator(mode="after")
    def honest_time(self) -> "TopicTime":
        if self.precision == "unknown":
            if any(value is not None for value in (self.at, self.on, self.basis)):
                raise ValueError("unknown topic time must remain unknown")
        elif self.precision == "date":
            if self.on is None or self.at is not None or not self.basis:
                raise ValueError("date precision requires only a supported date")
        elif (
            self.at is None or self.at.utcoffset() is None or self.on is not None or not self.basis
        ):
            raise ValueError("time precision requires only a supported timezone timestamp")
        return self


class DefineTopic(ContentContract):
    action: Literal["define"] = "define"
    kind: Literal["event", "issue"]
    title: Nonblank
    domains: tuple[str, ...] = Field(min_length=1, max_length=3)
    status: Literal["active", "archived"] = "active"

    @model_validator(mode="after")
    def known_domains(self) -> "DefineTopic":
        if len(set(self.domains)) != len(self.domains) or any(
            d not in DOMAINS for d in self.domains
        ):
            raise ValueError("topic domains must be distinct known domains")
        return self


class SetMember(ContentContract):
    action: Literal["member"] = "member"
    article_id: int = Field(gt=0)
    material_id: int = Field(gt=0)
    relation: Literal["report", "background", "opinion", "explanation", "reprint"]
    basis: Nonblank
    decision_version: Nonblank
    evidence: tuple[EvidenceRef, ...] = Field(min_length=1, max_length=20)


class RemoveMember(ContentContract):
    action: Literal["remove_member"] = "remove_member"
    article_id: int = Field(gt=0)


class RecordUpdate(ContentContract):
    action: Literal["update"] = "update"
    update_id: UUID
    summary: Nonblank
    decision_version: Nonblank
    evidence: tuple[EvidenceRef, ...] = Field(min_length=1, max_length=20)
    occurred: TopicTime = TopicTime()
    reported: TopicTime = TopicTime()


class RetractUpdate(ContentContract):
    action: Literal["retract_update"] = "retract_update"
    update_id: UUID


class TopicClaim(ContentContract):
    text: Nonblank
    evidence: tuple[EvidenceRef, ...] = Field(min_length=1, max_length=20)


class DerivationContract(ContentContract):
    version: Nonblank
    generation_model: Nonblank | None = None
    review_version: Nonblank
    review_model: Nonblank | None = None


class SaveDerivation(ContentContract):
    action: Literal["derivation"] = "derivation"
    kind: Literal["overview", "guide"]
    contract: DerivationContract
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    claims: tuple[TopicClaim, ...] = Field(min_length=1, max_length=30)


class TopicMutation(ContentContract):
    mutation_id: UUID
    expected_revision: int = Field(ge=0, le=2147483646)
    actor: Nonblank
    reason: Nonblank
    change: Annotated[
        DefineTopic | SetMember | RemoveMember | RecordUpdate | RetractUpdate | SaveDerivation,
        Field(discriminator="action"),
    ]
