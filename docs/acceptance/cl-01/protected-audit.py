"""CL-01 protected-state SELECT audit; no billing helper or provider requests."""

import json
from datetime import UTC, datetime

from sqlalchemy import create_engine, text
from unspun.core.config import get_settings

queries = {
    "schema": ("SELECT version_num FROM alembic_version"),
    "legacy_articles": (
        "SELECT count(*) AS rows, md5(string_agg(md5(row_to_json(a)::text), '' ORDER "
        "BY id)) AS row_hash FROM articles a WHERE processing_track='legacy'"
    ),
    "legacy_summary_pending": (
        "SELECT count(*) AS rows FROM articles WHERE processing_track='legacy' AND "
        "summary_failures < 3 AND (summary_zh IS NULL OR "
        "coalesce(((summary_grounding['reading'])->>'input_hash'), '') != md5(title || "
        "'\n' || coalesce(content, '')) OR "
        "summary_grounding->>'status'='review_limited' OR "
        "((summary_grounding['reading'])->>'reason') IN "
        "('language_invalid','title_unverified') OR "
        "coalesce(((summary_grounding['reading'])->>'version'), '') != 'reading-v1')"
    ),
    "legacy_summary_abandoned": (
        "SELECT count(*) AS rows FROM articles WHERE processing_track='legacy' AND "
        "summary_failures >= 3"
    ),
    "legacy_runs": (
        "SELECT count(*) AS rows, md5(string_agg(md5(row_to_json(t)::text), '' ORDER "
        "BY id)) AS row_hash FROM pipeline_runs t"
    ),
    "digests": (
        "SELECT count(*) AS rows, md5(string_agg(md5(row_to_json(t)::text), '' ORDER "
        "BY id)) AS row_hash FROM digests t"
    ),
    "source_ownership": (
        "SELECT owner,enabled,count(*) AS rows FROM source_states GROUP BY "
        "owner,enabled ORDER BY owner,enabled"
    ),
    "policy": (
        "SELECT scope,enabled,monthly_limit_usd,stage_caps,version,incident FROM budget_policy"
    ),
    "usage": ("SELECT count(*) AS rows,sum(cost_usd::numeric) AS known_usd FROM llm_usage"),
    "unknown": (
        "SELECT id,status,stage,reserved_usd,provider_generation_id FROM "
        "billed_requests WHERE status IN ('reserved','usage_unknown') ORDER BY id"
    ),
}
out = {"captured_at": datetime.now(UTC).isoformat(), "mode": "read-only", "queries": {}}
with (
    create_engine(get_settings().database_url)
    .connect()
    .execution_options(isolation_level="REPEATABLE READ") as conn
):
    tx = conn.begin()
    conn.execute(text("SET TRANSACTION READ ONLY"))
    conn.execute(text("SET LOCAL statement_timeout='30s'"))
    out["transaction"] = dict(
        conn.execute(
            text(
                "SELECT transaction_timestamp() AS at,current_database() AS database,"
                "current_setting('transaction_read_only') AS read_only"
            )
        )
        .mappings()
        .one()
    )
    for name, sql in queries.items():
        out["queries"][name] = {"sql": sql, "rows": list(conn.execute(text(sql)).mappings())}
    tx.rollback()
print(json.dumps(out, indent=2, default=lambda v: dict(v) if hasattr(v, "keys") else str(v)))
