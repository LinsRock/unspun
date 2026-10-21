"""Read-only ledger and retry history; no provider calls, allocations or task mutations."""

import json
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from unspun.core.billing import budget_status
from unspun.core.config import get_settings
from unspun.core.db import get_engine

out = {"at": datetime.now(UTC).isoformat(), "app_version": get_settings().app_version}
with get_engine().connect().execution_options(isolation_level="REPEATABLE READ") as conn:
    with conn.begin():
        conn.execute(text("SET TRANSACTION READ ONLY"))
        conn.execute(text("SET LOCAL statement_timeout='30s'"))

        def rows(sql):
            return [dict(row) for row in conn.execute(text(sql)).mappings()]

        out["database"] = conn.scalar(text("SELECT current_database()"))
        out["read_only"] = conn.scalar(text("SHOW transaction_read_only"))
        out["budget"] = budget_status(Session(bind=conn))
        out["known"] = rows("SELECT count(*) AS requests, sum(cost_usd::numeric) AS usd FROM llm_usage")[0]
        out["physical_count"] = conn.scalar(text("SELECT count(*) FROM billed_requests"))
        out["unresolved"] = rows("SELECT * FROM billed_requests WHERE status IN ('reserved','usage_unknown') ORDER BY started_at,id")
        out["affected_tasks"] = rows("SELECT * FROM pipeline_tasks WHERE id IN (SELECT task_id FROM billed_requests WHERE status IN ('reserved','usage_unknown') OR http_status=429) ORDER BY id")
        out["affected_attempts"] = rows("SELECT * FROM task_attempts WHERE task_id IN (SELECT task_id FROM billed_requests WHERE status IN ('reserved','usage_unknown') OR http_status=429) ORDER BY task_id,id")
        out["rate_limit_calls"] = rows("SELECT id,task_id,task_attempt_id,article_id,object_key,stage,phase,request_fingerprint,status,provider_generation_id,http_status,error,response_payload,reconciliation,started_at,ended_at,reserved_usd FROM billed_requests WHERE http_status=429 ORDER BY started_at,id")
        out["all_task_call_counts"] = rows("SELECT task_id,count(*) AS requests FROM billed_requests WHERE task_id IN (SELECT task_id FROM billed_requests WHERE http_status=429) GROUP BY task_id ORDER BY task_id")
        out["member_calls"] = rows("SELECT stage,status,count(*) AS requests FROM billed_requests WHERE stage LIKE 'topic_%' GROUP BY stage,status ORDER BY stage,status")
        out["protected_judgments"] = rows("SELECT * FROM member_judgments WHERE task_id=76")
        out["protected_task110"] = rows("SELECT * FROM pipeline_tasks WHERE id=110") if out["database"] != "unspun" else []
out.update(paid_requests=0, database_writes=0)
print(json.dumps(out, indent=2, default=str))
