"""Typed loader for config/scoring.yml."""

from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from unspun.core.config import get_settings


class FinalScoreWeights(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective: float
    importance: float
    relevance: float


class ImportanceWeights(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: float
    durability: float
    novelty: float


class ObjectiveWeights(BaseModel):
    model_config = ConfigDict(extra="forbid")

    breadth: float
    growth: float
    source_quality: float
    community: float


class ClusteringParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    similarity_threshold: float


class ObjectiveSignalsParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Log-saturation caps and monolocal discount for objective_score
    # (D-010). Defaults match config/scoring.yml; validation keeps a
    # tuning typo from silently flattening or inverting the score.
    source_cap: int = Field(default=15, ge=1)
    recent_cap: int = Field(default=10, ge=1)
    monolocal_discount: float = Field(default=0.7, gt=0.0, le=1.0)
    growth_window_hours: float = Field(default=24.0, gt=0.0)


class StreamParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    half_life_hours: float


class PipelineParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Defaults match the constants these replaced, so an older config
    # file without a pipeline section keeps the previous behavior.
    # ge=1: these are hand-tuned; a typo like 0 would silently stall the
    # worker, so a bad value must fail loudly at config load instead.
    summary_batch_limit: int = Field(default=50, ge=1)
    embed_batch_limit: int = Field(default=200, ge=1)
    score_batch_limit: int = Field(default=40, ge=1)
    max_summary_failures: int = Field(default=3, ge=1)


class ViewpointsParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Eligibility gate (D-011): an event earns a viewpoint comparison only
    # with enough independent coverage — at least min_sources distinct
    # sources spanning at least min_regions regions OR min_kinds kinds.
    min_sources: int = Field(default=3, ge=2)
    min_regions: int = Field(default=2, ge=1)
    min_kinds: int = Field(default=2, ge=1)
    # Per-cycle cap on LLM attempts (successful or not); bounds one cycle's
    # viewpoint spend even when outputs keep failing validation.
    viewpoint_batch_limit: int = Field(default=10, ge=1)


class DigestParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    digest_hour: int = Field(default=8, ge=0, le=23)
    digest_timezone: str = "Asia/Shanghai"
    top_n: int = Field(default=10, ge=1, le=200)

    @field_validator("digest_timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("digest_timezone must be an IANA timezone") from exc
        return value


class ScoringParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    final_score: FinalScoreWeights
    importance: ImportanceWeights
    objective: ObjectiveWeights
    clustering: ClusteringParams
    objective_signals: ObjectiveSignalsParams = ObjectiveSignalsParams()
    stream: StreamParams
    offcircle_ratio: float
    pipeline: PipelineParams = PipelineParams()
    viewpoints: ViewpointsParams = ViewpointsParams()
    digest: DigestParams = DigestParams()


def load_scoring_params(config_dir: str | Path | None = None) -> ScoringParams:
    base = Path(config_dir) if config_dir is not None else Path(get_settings().config_dir)
    raw = yaml.safe_load((base / "scoring.yml").read_text(encoding="utf-8"))
    return ScoringParams.model_validate(raw)


@lru_cache
def get_scoring_params() -> ScoringParams:
    return load_scoring_params()
