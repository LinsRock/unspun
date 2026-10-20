"""One-off CL-00 SELECT inventory; no processors, billing helpers or provider calls.

Run with the current server/src on PYTHONPATH. Optional database argument selects
an existing local database. --catalog enumerates existing databases only.
All result SQL and transaction settings are retained with the observations.
"""

import json
import sys
from datetime import UTC, datetime

import unspun
from sqlalchemy import create_engine, make_url, text
from unspun.core.config import get_settings

url = make_url(get_settings().database_url)
catalog = sys.argv[1:] == ["--catalog"]
if sys.argv[1:] and not catalog:
    url = url.set(database=sys.argv[1])
out = {
    "captured_at": datetime.now(UTC).isoformat(),
    "source_import": unspun.__file__,
    "paid_calls": 0,
    "manual_tasks": 0,
    "queries": {},
}
with create_engine(url).connect().execution_options(isolation_level="REPEATABLE READ") as conn:
    tx = conn.begin()
    conn.execute(text("SET TRANSACTION READ ONLY"))
    conn.execute(text("SET LOCAL statement_timeout = '30s'"))
    conn.execute(text("SET LOCAL lock_timeout = '3s'"))

    def query(name, sql):
        result = [dict(row) for row in conn.execute(text(sql)).mappings()]
        out["queries"][name] = {"sql": sql, "rows": result}
        return result

    query(
        "transaction",
        "SELECT transaction_timestamp() AS at, current_database() AS database, "
        "current_setting('transaction_read_only') AS read_only, "
        "current_setting('transaction_isolation') AS isolation, "
        "pg_database_size(current_database()) AS database_bytes",
    )
    query(
        "connections",
        "SELECT datname, application_name, state, count(*) AS connections "
        "FROM pg_stat_activity WHERE pid <> pg_backend_pid() "
        "GROUP BY datname,application_name,state ORDER BY datname,application_name,state",
    )
    if catalog:
        query(
            "databases",
            "SELECT datname, pg_get_userbyid(datdba) AS owner, "
            "pg_database_size(oid) AS bytes FROM pg_database "
            "WHERE NOT datistemplate ORDER BY datname",
        )
    else:
        tables = query(
            "relations",
            "SELECT c.relname AS name, "
            "pg_relation_size(c.oid) AS heap_bytes, "
            "pg_table_size(c.oid) AS table_bytes, "
            "pg_indexes_size(c.oid) AS index_bytes, "
            "pg_total_relation_size(c.oid) AS total_bytes "
            "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='public' AND c.relkind='r' ORDER BY c.relname",
        )
        names = {row["name"] for row in tables}
        columns = query(
            "columns",
            "SELECT table_name,column_name FROM information_schema.columns "
            "WHERE table_schema='public' ORDER BY table_name,ordinal_position",
        )
        colset = {(r["table_name"], r["column_name"]) for r in columns}
        for row in tables:
            name = row["name"]
            assert name.replace("_", "").isalnum()
            query("count:" + name, f'SELECT count(*) AS rows FROM "{name}"')
        query(
            "foreign_keys",
            "SELECT conrelid::regclass::text AS child, conname AS name, "
            "confrelid::regclass::text AS parent, pg_get_constraintdef(oid) AS definition "
            "FROM pg_constraint WHERE contype='f' AND connamespace='public'::regnamespace "
            "ORDER BY child,name",
        )
        if "alembic_version" in names:
            query("schema", "SELECT * FROM alembic_version")
        if ("articles", "processing_track") in colset:
            query(
                "article_tracks",
                "SELECT processing_track,count(*) AS rows, "
                "sum(octet_length(coalesce(content,''))) AS content_bytes, "
                "count(*) FILTER (WHERE event_id IS NOT NULL) AS event_linked, "
                "count(*) FILTER (WHERE canonical_content_id IS NOT NULL) AS aliases, "
                "count(*) FILTER (WHERE current_material_id IS NOT NULL) AS current_material, "
                "min(fetched_at) AS first_at,max(fetched_at) AS last_at "
                "FROM articles GROUP BY processing_track ORDER BY processing_track",
            )
        if "content_materials" in names:
            query(
                "materials",
                "SELECT scope,access_status,count(*) AS rows, "
                "sum(pg_column_size(m)) AS logical_row_bytes, "
                "count(*) FILTER (WHERE a.current_material_id=m.id) AS current_pointers, "
                "count(*) FILTER (WHERE EXISTS (SELECT 1 FROM content_derivations d "
                "WHERE d.material_id=m.id AND d.article_id=m.article_id)) AS derived, "
                "min(retrieved_at) AS first_at,max(retrieved_at) AS last_at "
                "FROM content_materials m JOIN articles a ON a.id=m.article_id "
                "GROUP BY scope,access_status ORDER BY scope,access_status",
            )
            query(
                "material_candidates",
                "SELECT count(*) AS noncurrent_without_derivation, "
                "coalesce(sum(pg_column_size(m)),0) AS logical_row_bytes "
                "FROM content_materials m JOIN articles a ON a.id=m.article_id "
                "WHERE a.current_material_id IS DISTINCT FROM m.id AND NOT EXISTS "
                "(SELECT 1 FROM content_derivations d WHERE d.material_id=m.id "
                "AND d.article_id=m.article_id)",
            )
            query(
                "material_duplicates",
                "SELECT count(*) AS fingerprint_groups, "
                "coalesce(sum(n-1),0) AS extra_rows FROM (SELECT text_fingerprint,count(*) AS n "
                "FROM content_materials WHERE text_fingerprint IS NOT NULL "
                "GROUP BY text_fingerprint HAVING count(*)>1) d",
            )
        for table, dims, stamp in (
            ("content_derivations", "kind,status", "updated_at"),
            ("pipeline_tasks", "queue,kind,status", "created_at"),
            ("task_attempts", "status", "started_at"),
            ("content_observations", "source_id", "observed_at"),
            ("discovery_batches", "source_id,version", "observed_at"),
            ("fetch_logs", "status", "run_at"),
        ):
            if table in names:
                query(
                    table + "_groups",
                    f"SELECT {dims},count(*) AS rows, "
                    f"min({stamp}) AS first_at,max({stamp}) AS last_at, "
                    f"count(*) FILTER (WHERE {stamp} >= "
                    "transaction_timestamp()-interval '24 hours') "
                    f"AS last_24h_rows FROM {table} GROUP BY {dims} ORDER BY {dims}",
                )
        if "source_states" in names:
            query(
                "source_owners",
                "SELECT owner,enabled,count(*) AS rows FROM source_states "
                "GROUP BY owner,enabled ORDER BY owner,enabled",
            )
        if "discovery_batches" in names:
            query(
                "quota_references",
                "SELECT count(*) AS tasks_with_quota_batch, "
                "count(*) FILTER (WHERE EXISTS (SELECT 1 FROM discovery_batches b "
                "WHERE b.id::text=t.payload->>'quota_batch_id')) AS matched "
                "FROM pipeline_tasks t WHERE payload ? 'quota_batch_id'",
            )
            query(
                "quota_receipt_keys",
                "SELECT count(*) AS rows, "
                "count(DISTINCT (source_id,cycle_key)) AS unique_keys FROM discovery_batches",
            )
        if "billed_requests" in names:
            query(
                "request_groups",
                "SELECT stage,status,count(*) AS rows, "
                "sum(reserved_usd) AS reserved_usd, sum(u.cost_usd::numeric) AS known_usd, "
                "count(task_id) AS task_links,count(article_id) AS article_links "
                "FROM billed_requests b LEFT JOIN llm_usage u ON u.id=b.usage_id "
                "GROUP BY stage,status ORDER BY stage,status",
            )
            query(
                "unresolved_requests",
                "SELECT id,status,stage,article_id,task_id,task_attempt_id, "
                "provider_generation_id,reserved_usd,started_at,ended_at,http_status "
                "FROM billed_requests WHERE status IN ('reserved','usage_unknown') ORDER BY id",
            )
            query(
                "policy",
                "SELECT scope,enabled,monthly_limit_usd,stage_caps,version,incident "
                "FROM budget_policy",
            )
            query("carry", "SELECT * FROM budget_carry")
        if "llm_usage" in names:
            query(
                "known_usage",
                "SELECT purpose,count(*) AS rows,sum(cost_usd::numeric) AS usd "
                "FROM llm_usage GROUP BY purpose ORDER BY purpose",
            )
        if "pipeline_runs" in names:
            query(
                "legacy_runs",
                "SELECT count(*) AS rows,min(run_at) AS first_at,max(run_at) "
                "AS last_at FROM pipeline_runs",
            )
        if "digests" in names:
            query(
                "digest_range",
                "SELECT count(*) AS rows,min(report_date) AS first_date,max(report_date) "
                "AS last_date FROM digests",
            )
    tx.rollback()
print(json.dumps(out, indent=2, default=str, ensure_ascii=True))
