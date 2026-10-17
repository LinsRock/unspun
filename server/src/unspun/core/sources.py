"""Typed loader for config/sources.yml."""

from pathlib import Path
from typing import Annotated, Literal, cast

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    ValidationInfo,
    field_validator,
    model_validator,
)

from unspun.core.config import get_settings
from unspun.core.content import ContentForm, MaterialScope

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


class R1Source(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    adapter: Literal["rss", "zhihu_daily", "people_daily", "thepaper", "netease", "tencent"] = "rss"
    discovery: bool = False
    material: bool = False
    paid: bool = False
    publish: bool = False
    paid_scopes: tuple[MaterialScope, ...] | None = None
    publish_scopes: tuple[MaterialScope, ...] | None = None
    period_seconds: int = Field(default=1800, ge=60)
    form: ContentForm = "article"
    material_scope: MaterialScope = "open_text_unit"
    platform: str | None = None
    publisher: str | None = None
    origin_hosts: tuple[str, ...] = ()
    capability: str = "unverified"
    version: str = "r1-discovery-v1"

    def allows_paid(self, scope: str) -> bool:
        return self.paid and (self.paid_scopes is None or scope in self.paid_scopes)

    def allows_publication(self, scope: str) -> bool:
        return self.publish and (self.publish_scopes is None or scope in self.publish_scopes)


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    url: HttpUrl
    weight: float
    region: Region
    kind: Kind
    lang: Literal["zh", "en"]
    max_items: int | None = Field(default=None, ge=1, le=200)
    legacy_enabled: bool = True
    discovery_owner: Literal["legacy", "r1"] = "legacy"
    r1: R1Source | None = None
    # RSSHub routes fetch article pages on a cold cache and can take far
    # longer than a plain feed; sources that need it override the client
    # default here.
    timeout_seconds: Annotated[int, Field(gt=0)] | None = None

    @model_validator(mode="after")
    def single_owner(self) -> "Source":
        if self.discovery_owner == "r1" and self.legacy_enabled:
            raise ValueError("R1 ownership requires legacy discovery to be disabled")
        if (
            self.r1
            and any((self.r1.discovery, self.r1.material, self.r1.paid, self.r1.publish))
            and self.discovery_owner != "r1"
        ):
            raise ValueError("enabled R1 stages require R1 discovery ownership")
        return self

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
