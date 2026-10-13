"""Approved public configuration fields for the read-only admin view."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from unspun.core.config import Settings, get_settings
from unspun.core.params import load_scoring_params
from unspun.core.sources import load_sources

router = APIRouter()


class SourceConfiguration(BaseModel):
    id: str
    name: str
    weight: float
    region: str
    kind: str
    lang: str
    max_items: int | None
    timeout_seconds: int | None


class PipelineConfiguration(BaseModel):
    fetch_interval_minutes: int
    summary_batch_limit: int
    embed_batch_limit: int
    score_batch_limit: int
    max_summary_failures: int
    digest_hour: int
    digest_timezone: str
    grounding_budget_24h_usd: float
    summary_model: str
    importance_model: str
    viewpoint_model: str
    digest_model: str
    embedding_model: str


class CredentialsStatus(BaseModel):
    openrouter_configured: bool


class AuditStatus(BaseModel):
    status: Literal["not_recorded"] = "not_recorded"
    message: str = "Historical configuration and operation audit was not recorded"


class ConfigurationOut(BaseModel):
    sources: list[SourceConfiguration]
    pipeline: PipelineConfiguration
    credentials: CredentialsStatus
    audit: AuditStatus


@router.get("/configuration", response_model=ConfigurationOut)
def get_configuration(settings: Annotated[Settings, Depends(get_settings)]) -> ConfigurationOut:
    params = load_scoring_params(settings.config_dir)
    sources = load_sources(settings.config_dir, settings.rsshub_url)
    return ConfigurationOut(
        sources=[
            SourceConfiguration(**source.model_dump(include=set(SourceConfiguration.model_fields)))
            for source in sources
        ],
        pipeline=PipelineConfiguration(
            fetch_interval_minutes=settings.fetch_interval_minutes,
            summary_batch_limit=params.pipeline.summary_batch_limit,
            embed_batch_limit=params.pipeline.embed_batch_limit,
            score_batch_limit=params.pipeline.score_batch_limit,
            max_summary_failures=params.pipeline.max_summary_failures,
            digest_hour=params.digest.digest_hour,
            digest_timezone=params.digest.digest_timezone,
            grounding_budget_24h_usd=settings.grounding_budget_24h_usd,
            summary_model=settings.summary_model,
            importance_model=settings.importance_model,
            viewpoint_model=settings.viewpoint_model,
            digest_model=settings.digest_model,
            embedding_model=settings.embedding_model,
        ),
        credentials=CredentialsStatus(openrouter_configured=bool(settings.openrouter_api_key)),
        audit=AuditStatus(),
    )
