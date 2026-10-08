from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="UNSPUN_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://unspun:unspun@localhost:5432/unspun"
    app_version: str = "dev"
    log_json: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
