"""Compact read-only R2-04 ledger/runtime snapshot; optional free provider key GET."""

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
import unspun
from sqlalchemy import text
from sqlalchemy.orm import Session

from unspun.core.billing import budget_status
from unspun.core.billing_admin import provider_key_status
from unspun.core.config import get_settings
from unspun.core.content_reading import CARD_VERSION, GUIDE_VERSION, REVIEW_VERSION
from unspun.core.db import get_engine
from unspun.core.sources import load_sources

mode = sys.argv[1]
settings = get_settings()
out = {
    "schema_version": "r2-04-readonly-v1",
    "mode": mode,
    "started_at": datetime.now(UTC).isoformat(),
}
with get_engine().connect().execution_options(isolation_level="REPEATABLE READ") as conn:
    tx = conn.begin()
    conn.execute(text("SET TRANSACTION READ ONLY"))
    conn.execute(text("SET LOCAL statement_timeout='30s'"))

    def query(sql):
        return [dict(row) for row in conn.execute(text(sql)).mappings()]

    session = Session(bind=conn)
    out["transaction"] = query(
        "SELECT transaction_timestamp() AS at,current_database() AS database,current_setting('transaction_read_only') AS read_only"
    )[0]
    out["schema"] = query("SELECT version_num FROM alembic_version")
    out["budget"] = budget_status(session)
    out["known_ledger"] = query(
        "SELECT count(*) AS requests,sum(cost_usd::numeric) AS known_usd FROM llm_usage"
    )
    out["unknown_requests"] = query(
        "SELECT id,stage,phase,model,status,reserved_usd,provider_generation_id,started_at FROM billed_requests WHERE status IN ('reserved','usage_unknown') ORDER BY id"
    )
    out["policy"] = query(
        "SELECT scope,enabled,monthly_limit_usd,stage_caps,version,incident,provider_limit_usd,provider_usage_usd,provider_observed_at FROM budget_policy"
    )
    out["carry"] = query("SELECT * FROM budget_carry ORDER BY month")
    if mode == "production":
        out["app_version"] = settings.app_version
        out["contracts"] = {
            "card": CARD_VERSION,
            "guide": GUIDE_VERSION,
            "review": REVIEW_VERSION,
        }
        out["models"] = {
            key: getattr(settings, key)
            for key in (
                "summary_model",
                "importance_model",
                "viewpoint_model",
                "digest_model",
                "embedding_model",
                "grounding_budget_24h_usd",
            )
        }
        out["sources"] = [source.model_dump(mode="json") for source in load_sources() if source.r1]
        out["source_sha256"] = {
            str(p.relative_to(Path(unspun.__file__).parent)): hashlib.sha256(
                p.read_bytes()
            ).hexdigest()
            for p in sorted(Path(unspun.__file__).parent.rglob("*.py"))
        }
        out["config_sha256"] = {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(settings.config_dir).glob("*.yml"))
        }
        out["articles"] = query(
            "SELECT a.id,a.source_id,a.url,a.title,a.canonical_content_id,m.scope,m.access_status,m.text_fingerprint,m.metadata_fingerprint FROM articles a LEFT JOIN content_materials m ON m.id=a.current_material_id WHERE a.processing_track='r1' ORDER BY a.id"
        )
        out["source_states"] = query("SELECT * FROM source_states ORDER BY source_id")
        out["card_attempt_status"] = query(
            "SELECT status,count(*) AS tasks FROM pipeline_tasks WHERE kind='process_card' GROUP BY status ORDER BY status"
        )
    session.close()
    tx.rollback()
if mode == "production":
    with httpx.Client(
        base_url=settings.openrouter_base_url,
        headers={"Authorization": "Bearer " + settings.openrouter_api_key},
        timeout=30,
    ) as client:
        status = provider_key_status(client)
    out["provider"] = {
        key: status.get(key)
        for key in ("limit", "limit_remaining", "limit_reset", "usage", "usage_monthly")
    }
    out["provider"].update(checked_at=datetime.now(UTC).isoformat(), method="GET /api/v1/key")
out.update(completed_at=datetime.now(UTC).isoformat(), paid_requests=0, database_writes=0)
print(json.dumps(out, ensure_ascii=False, default=str, indent=2))
