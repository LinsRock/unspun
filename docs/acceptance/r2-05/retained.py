"""Read-only retained Event, identity, and reader resource hashes."""

import json
from datetime import UTC, datetime

from sqlalchemy import text
from unspun.core.db import get_engine

tables = (
    "events",
    "reader_state",
    "reader_interests",
    "content_feedback",
    "reader_changes",
    "content_identities",
    "content_urls",
)
out = {"captured_at": datetime.now(UTC).isoformat(), "tables": {}}
with (
    get_engine().connect().execution_options(isolation_level="REPEATABLE READ") as conn,
    conn.begin(),
):
    conn.execute(text("SET TRANSACTION READ ONLY"))
    out["read_only"] = conn.scalar(
        text("SELECT current_setting('transaction_read_only')")
    )
    for table in tables:
        out["tables"][table] = dict(
            conn.execute(
                text(
                    "SELECT count(*) AS rows,md5(string_agg(to_jsonb(t)::text,'' ORDER BY to_jsonb(t)::text)) AS hash FROM "
                    + table
                    + " t"
                )
            )
            .mappings()
            .one()
        )
print(json.dumps(out, indent=2))
