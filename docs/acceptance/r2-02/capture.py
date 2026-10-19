"""One-off SELECT-only R2-02 deployment and quota evidence; never runs processors."""

import hashlib
import json
import sys
from pathlib import Path

import httpx
import unspun
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.orm import Session
from unspun.core.billing import budget_status
from unspun.core.billing_admin import provider_key_status
from unspun.core.config import get_settings
from unspun.core.sources import load_sources

mode = sys.argv[1]
assert mode in {"production", "evaluation"}
settings = get_settings()
url = make_url(settings.database_url)
if mode == "evaluation":
    url = url.set(database="unspun_quality_r1_20261016")
out = {"version": "r2-02-readonly-v2", "mode": mode, "capture_paid_calls": 0}
with (
    create_engine(url)
    .connect()
    .execution_options(isolation_level="REPEATABLE READ") as conn
):
    tx = conn.begin()
    conn.execute(text("SET TRANSACTION READ ONLY"))
    conn.execute(text("SET LOCAL statement_timeout = '30s'"))

    def query(sql):
        return [dict(row) for row in conn.execute(text(sql)).mappings()]

    out["transaction"] = query(
        "SELECT transaction_timestamp() AS at, current_database() AS database, "
        "current_setting('transaction_read_only') AS read_only"
    )[0]
    out["schema"] = query("SELECT version_num FROM alembic_version")
    out["policy"] = query(
        "SELECT scope, monthly_limit_usd, stage_caps, version, incident FROM budget_policy"
    )
    out["budget"] = budget_status(Session(bind=conn))
    out["requests"] = query(
        "SELECT stage, status, count(*) AS requests, sum(reserved_usd) AS reserved_usd, "
        "sum(u.cost_usd::numeric) AS known_usd, count(DISTINCT b.article_id) AS contents "
        "FROM billed_requests b LEFT JOIN llm_usage u ON u.id=b.usage_id "
        "GROUP BY stage,status ORDER BY stage,status"
    )
    if mode == "production":
        out["app_version"] = settings.app_version
        out["source_sha256"] = {
            str(p.relative_to(Path(unspun.__file__).parent)): hashlib.sha256(
                p.read_bytes()
            ).hexdigest()
            for p in sorted(Path(unspun.__file__).parent.rglob("*.py"))
        }
        out["sources"] = [
            {"id": s.id, "max_items": s.max_items, "r1": s.r1.model_dump(mode="json")}
            for s in load_sources()
            if s.r1 and s.r1.discovery
        ]
        out["models"] = {
            key: getattr(settings, key)
            for key in (
                "summary_model",
                "viewpoint_model",
                "embedding_model",
                "grounding_budget_24h_usd",
            )
        }
        out["source_states"] = query(
            "SELECT * FROM source_states WHERE enabled ORDER BY source_id"
        )
        out["tasks"] = query(
            "SELECT queue,status,count(*) AS tasks FROM pipeline_tasks GROUP BY queue,status "
            "ORDER BY queue,status"
        )
        if conn.scalar(text("SELECT to_regclass('discovery_batches')")) is not None:
            out["discovery_batches"] = query(
                "SELECT * FROM discovery_batches ORDER BY id"
            )
        else:
            out["discovery_batches"] = None
    tx.rollback()
if mode == "production":
    with httpx.Client(
        base_url=settings.openrouter_base_url,
        headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
        timeout=30,
    ) as client:
        data = provider_key_status(client)
        out["provider"] = {
            key: data.get(key)
            for key in (
                "limit",
                "limit_remaining",
                "usage",
                "usage_monthly",
                "limit_reset",
            )
        }
print(json.dumps(out, ensure_ascii=True, default=str, indent=2))
