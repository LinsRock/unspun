"""Typed loader for config/sources.yml."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, HttpUrl

from unspun.core.config import get_settings

Region = Literal["cn-mainland", "hk-tw", "us", "eu", "jp", "me", "intl"]
Kind = Literal[
    "wire",
    "public",
    "commercial",
    "state",
    "independent",
    "community",
    "academic",
    "official",
]


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    url: HttpUrl
    weight: float
    region: Region
    kind: Kind
    lang: Literal["zh", "en"]
    max_items: int | None = None


class SourcesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sources: list[Source]


def load_sources(config_dir: str | Path | None = None) -> list[Source]:
    """Load and validate the source list; raises on duplicate ids."""
    base = Path(config_dir) if config_dir is not None else Path(get_settings().config_dir)
    raw = yaml.safe_load((base / "sources.yml").read_text(encoding="utf-8"))
    sources = SourcesFile.model_validate(raw).sources
    ids = [s.id for s in sources]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f"duplicate source ids: {sorted(duplicates)}")
    return sources
