"""Typed loader for config/scoring.yml."""

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

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


class ScoringParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    final_score: FinalScoreWeights
    importance: ImportanceWeights
    objective: ObjectiveWeights
    clustering: ClusteringParams
    stream: StreamParams
    offcircle_ratio: float
    pipeline: PipelineParams = PipelineParams()


def load_scoring_params(config_dir: str | Path | None = None) -> ScoringParams:
    base = Path(config_dir) if config_dir is not None else Path(get_settings().config_dir)
    raw = yaml.safe_load((base / "scoring.yml").read_text(encoding="utf-8"))
    return ScoringParams.model_validate(raw)


@lru_cache
def get_scoring_params() -> ScoringParams:
    return load_scoring_params()
