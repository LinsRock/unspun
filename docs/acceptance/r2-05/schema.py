"""SELECT-only deployed topic schema and empty-table audit; no backfill."""

import json
from datetime import UTC, datetime

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from unspun.core.db import get_engine

tables = (
    "topics",
    "topic_members",
    "topic_changes",
    "topic_updates",
    "topic_derivations",
)
out = {
    "captured_at": datetime.now(UTC).isoformat(),
    "migration_heads": ScriptDirectory.from_config(Config("alembic.ini")).get_heads(),
    "tables": {},
}
with get_engine().connect() as conn, conn.begin():
    conn.execute(text("SET TRANSACTION READ ONLY"))
    out["read_only"] = conn.scalar(
        text("SELECT current_setting('transaction_read_only')")
    )
    out["schema"] = conn.scalar(text("SELECT version_num FROM alembic_version"))
    for table in tables:
        out["tables"][table] = {
            "rows": conn.scalar(text("SELECT count(*) FROM " + table)),
            "constraints": [
                dict(row)
                for row in conn.execute(
                    text(
                        "SELECT conname,contype,pg_get_constraintdef(oid) AS definition FROM pg_constraint WHERE conrelid=to_regclass(:table) ORDER BY conname"
                    ),
                    {"table": table},
                ).mappings()
            ],
        }
out.update(database_writes=0, paid_requests=0)
print(json.dumps(out, indent=2))
