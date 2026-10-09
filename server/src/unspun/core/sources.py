"""Typed loader for config/sources.yml."""

from pathlib import Path
from typing import Annotated, Literal, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationInfo, field_validator

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


RSSHUB_SCHEME = "rsshub://"


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
    # RSSHub routes fetch article pages on a cold cache and can take far
    # longer than a plain feed; sources that need it override the client
    # default here.
    timeout_seconds: Annotated[int, Field(gt=0)] | None = None

    @field_validator("url", mode="before")
    @classmethod
    def _resolve_rsshub(cls, value: object, info: ValidationInfo) -> object:
        if isinstance(value, str) and value.startswith(RSSHUB_SCHEME):
            context = cast("dict[str, object]", info.context or {})
            base = context.get("rsshub_base")
            if not isinstance(base, str):
                base = get_settings().rsshub_url
            return resolve_rsshub_url(value, base)
        return value


def resolve_rsshub_url(url: str, rsshub_base: str) -> str:
    """Expand rsshub://<route> against the configured RSSHub base URL."""
    if not url.startswith(RSSHUB_SCHEME):
        return url
    return f"{rsshub_base.rstrip('/')}/{url[len(RSSHUB_SCHEME) :]}"


class SourcesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sources: list[Source]


def load_sources(
    config_dir: str | Path | None = None, rsshub_base: str | None = None
) -> list[Source]:
    """Load and validate the source list; raises on duplicate ids.

    rsshub:// URLs resolve against rsshub_base (default: settings.rsshub_url).
    """
    base = Path(config_dir) if config_dir is not None else Path(get_settings().config_dir)
    raw = yaml.safe_load((base / "sources.yml").read_text(encoding="utf-8"))
    context = {"rsshub_base": rsshub_base or get_settings().rsshub_url}
    sources = SourcesFile.model_validate(raw, context=context).sources
    ids = [s.id for s in sources]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f"duplicate source ids: {sorted(duplicates)}")
    return sources
