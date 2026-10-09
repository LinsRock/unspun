"""Typed loader for config/scoring.yml."""

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

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


class ScoringParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    final_score: FinalScoreWeights
    importance: ImportanceWeights
    objective: ObjectiveWeights
    clustering: ClusteringParams
    stream: StreamParams
    offcircle_ratio: float


def load_scoring_params(config_dir: str | Path | None = None) -> ScoringParams:
    base = Path(config_dir) if config_dir is not None else Path(get_settings().config_dir)
    raw = yaml.safe_load((base / "scoring.yml").read_text(encoding="utf-8"))
    return ScoringParams.model_validate(raw)


@lru_cache
def get_scoring_params() -> ScoringParams:
    return load_scoring_params()
