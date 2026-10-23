"""Versioned, evidence-only hybrid recall. No producers or inferred attention."""

from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

import yaml
from pydantic import AwareDatetime, Field, HttpUrl, StrictInt, model_validator

from unspun.core.config import get_settings
from unspun.core.content import ContentContract
from unspun.core.topic_contracts import EvidenceRef

VERSION = "r2-hybrid-v1"
Lane = Literal["important", "interest", "public_attention", "readable"]
Kind = Literal["content", "topic"]


class Signal(ContentContract):
    id: str = Field(min_length=1, max_length=120)
    type: Kind
    target_id: str = Field(min_length=1, max_length=80)
    target_version: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: Literal["important", "public_attention"]
    origin: Literal["observed", "engineering_fixture"]
    observed_at: AwareDatetime
    expires_at: AwareDatetime
    reason: str = Field(min_length=1, max_length=1000)
    reviewer: str = Field(min_length=1, max_length=200)
    evidence_url: HttpUrl
    metric: Literal["public_impact", "interactions", "rank"]
    raw_value: StrictInt = Field(gt=0)
    evidence: tuple[EvidenceRef, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def meaningful_basis(self) -> "Signal":
        if self.type == "content":
            if (
                not self.target_id.isascii()
                or not self.target_id.isdecimal()
                or not 0 < int(self.target_id) < 2**63
            ):
                raise ValueError("content signals require a positive canonical integer ID")
        elif str(UUID(self.target_id)) != self.target_id:
            raise ValueError("topic signals require a canonical UUID")
        if self.expires_at <= self.observed_at:
            raise ValueError("signal expiry must follow observation")
        if self.kind == "important":
            if self.metric != "public_impact" or not self.evidence:
                raise ValueError("importance requires reviewed public impact and material evidence")
        elif self.metric not in {"interactions", "rank"}:
            raise ValueError("attention requires a direct public observation")
        return self

    def current(self, now: datetime) -> bool:
        return self.observed_at <= now < self.expires_at


class HybridRules(ContentContract):
    version: Literal["r2-hybrid-v1"] = VERSION
    content_lane_limit: int = Field(default=120, ge=1, le=120)
    readable_limit: int = Field(default=240, ge=1, le=240)
    topic_lane_limit: int = Field(default=8, ge=1, le=8)
    topic_member_limit: int = Field(default=16, ge=1, le=16)
    topic_update_limit: int = Field(default=32, ge=1, le=32)
    importance_weight: float = Field(default=2, ge=0, le=3)
    attention_weight: float = Field(default=1, ge=0, le=3)
    topic_follow_weight: float = Field(default=2, ge=0, le=2)
    signals: tuple[Signal, ...] = Field(default=(), max_length=256)

    @model_validator(mode="after")
    def observed_only(self) -> "HybridRules":
        if any(s.origin != "observed" for s in self.signals):
            raise ValueError("engineering signals cannot enter the runtime registry")
        keys = [(s.type, s.target_id, s.kind) for s in self.signals]
        if len(set(keys)) != len(keys) or len({s.id for s in self.signals}) != len(keys):
            raise ValueError("signal registry must have unique IDs and target/kind pairs")
        return self


def hybrid_rules() -> HybridRules:
    return HybridRules.model_validate(
        yaml.safe_load((Path(get_settings().config_dir) / "r2-hybrid.yml").read_text())
    )


class HybridCursor(ContentContract):
    version: Literal["r2-hybrid-v1"] = VERSION
    sort: Literal["recommended", "latest"]
    as_of: AwareDatetime
    snapshot: str = Field(pattern=r"^[0-9a-f]{64}$")
    offset: StrictInt = Field(ge=1, le=632)
    page_size: StrictInt = Field(ge=1, le=50)
