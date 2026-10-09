from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="UNSPUN_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://unspun:unspun@localhost:5432/unspun"
    app_version: str = "dev"
    log_json: bool = True
    # Default fits local dev (run from server/); the container image sets
    # UNSPUN_CONFIG_DIR=/app/config.
    config_dir: str = "../config"
    fetch_interval_minutes: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
