from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="UNSPUN_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://unspun:unspun@localhost:5432/unspun"
    app_version: str = "dev"
    access_team_domain: str = ""
    access_audience: str = ""
    admin_local_preview: bool = False
    r1_local_preview: bool = False
    r1_worker_enabled: bool = False
    r2_member_processing_enabled: bool = False
    r2_synthesis_enabled: bool = False
    r2_topic_publication_enabled: bool = False
    log_json: bool = True
    # Default fits local dev (run from server/); the container image sets
    # UNSPUN_CONFIG_DIR=/app/config.
    config_dir: str = "../config"
    fetch_interval_minutes: int = 30
    # Self-hosted RSSHub base URL (rsshub:// source URLs resolve against it
    # from M2 T2 on). Default fits the compose network; host-run dev points
    # it at the loopback mapping from deploy/compose.local.yml.
    rsshub_url: str = "http://rsshub:1200"

    # OpenRouter covers both chat and embeddings; one key for everything.
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    summary_model: str = "google/gemini-2.5-flash-lite"
    importance_model: str = "google/gemini-2.5-flash"
    # Viewpoint comparison and semantic grounding review use the flash tier.
    # Evidence inputs and review behavior follow D-013.
    viewpoint_model: str = "google/gemini-2.5-flash"
    grounding_budget_24h_usd: float = Field(default=0.40, ge=0, allow_inf_nan=False)
    digest_model: str = "google/gemini-2.5-flash-lite"
    embedding_model: str = "qwen/qwen3-embedding-8b"


@lru_cache
def get_settings() -> Settings:
    return Settings()
