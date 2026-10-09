from fastapi import FastAPI
from pydantic import BaseModel
from sqlalchemy import text

from unspun.api.events import router as events_router
from unspun.api.report import router as report_router
from unspun.core.config import get_settings
from unspun.core.db import get_engine
from unspun.core.logging import configure_logging, get_logger

configure_logging()
log = get_logger("unspun.api")

app = FastAPI(title="Unspun API", docs_url=None, redoc_url=None)
app.include_router(events_router)
app.include_router(report_router)


class HealthResponse(BaseModel):
    status: str
    version: str
    database: str


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        database = "ok"
    except Exception:
        log.exception("health_db_check_failed")
        database = "error"
    status = "ok" if database == "ok" else "degraded"
    return HealthResponse(status=status, version=settings.app_version, database=database)
