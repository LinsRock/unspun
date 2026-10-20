"""Restore a read-only production backup into a fresh local DB, then rehearse additive migration."""

import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

ROOT = Path(__file__).resolve().parents[3]
database = "unspun_r205_prod_restore_20261020"
private = Path.home() / ".cache/unspun-r205-20261020"
private.mkdir(parents=True, exist_ok=True)
backup = private / "predeploy-production-schema-000017-v2.dump"
started = datetime.now(UTC).isoformat()
with backup.open("xb") as handle:
    subprocess.run(
        ["ssh", "unspun", "docker exec unspun-db-1 pg_dump -U unspun -d unspun -Fc"],
        stdout=handle,
        check=True,
        timeout=300,
    )
subprocess.run(
    ["docker", "exec", "unspun-db-1", "createdb", "-U", "unspun", database], check=True
)
with backup.open("rb") as handle:
    subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            "unspun-db-1",
            "pg_restore",
            "-U",
            "unspun",
            "-d",
            database,
            "--exit-on-error",
            "--no-owner",
        ],
        stdin=handle,
        check=True,
        timeout=60,
    )
environment = dict(
    os.environ,
    UNSPUN_DATABASE_URL="postgresql+psycopg://unspun:unspun@localhost:5432/" + database,
)
engine = create_engine(environment["UNSPUN_DATABASE_URL"])


def snapshot():
    with engine.connect() as conn, conn.begin():
        conn.execute(text("SET TRANSACTION READ ONLY"))
        result = {}
        for table in inspect(conn).get_table_names():
            quoted = conn.dialect.identifier_preparer.quote(table)
            result[table] = dict(
                conn.execute(
                    text(
                        f"SELECT count(*) AS rows,md5(string_agg(to_jsonb(t)::text,'' ORDER BY to_jsonb(t)::text)) AS hash FROM {quoted} t"
                    )
                )
                .mappings()
                .one()
            )
        return result


before = snapshot()
reading_script = (ROOT / "docs/acceptance/r2-04/reading.py").read_text()
reading_before = json.loads(
    subprocess.check_output(
        [sys.executable, "-"],
        input=reading_script,
        text=True,
        env=environment,
        cwd=ROOT / "server",
        timeout=60,
    )
)
migration = subprocess.run(
    [sys.executable, "-m", "alembic", "upgrade", "head"],
    cwd=ROOT / "server",
    env=environment,
    capture_output=True,
    text=True,
    timeout=30,
)
assert migration.returncode == 0, migration.stderr
after = snapshot()
assert all(after[k] == v for k, v in before.items() if k != "alembic_version")
assert all(after[k]["rows"] == 0 for k in set(after) - set(before))
reading_after = json.loads(
    subprocess.check_output(
        [sys.executable, "-"],
        input=reading_script,
        text=True,
        env=environment,
        cwd=ROOT / "server",
        timeout=60,
    )
)
assert all(
    reading_before[k] == reading_after[k] for k in reading_before if k != "captured_at"
)
report = {
    "started_at": started,
    "completed_at": datetime.now(UTC).isoformat(),
    "production_mode": "read-only pg_dump; no production writes or restore",
    "isolated_database": database,
    "backup": {
        "path": str(backup),
        "sha256": hashlib.sha256(backup.read_bytes()).hexdigest(),
        "bytes": backup.stat().st_size,
    },
    "before": before,
    "after": after,
    "migration": {
        "returncode": migration.returncode,
        "stdout": migration.stdout,
        "stderr": migration.stderr,
    },
    "all_old_table_counts_and_hashes_preserved": True,
    "new_tables_empty": True,
    "reading_contract_unchanged": True,
    "reading": reading_after,
    "paid_requests": 0,
    "retained_backup_and_isolated_database": True,
}
Path(__file__).with_name("production-restore.json").write_text(
    json.dumps(report, ensure_ascii=False, default=str, indent=2) + "\n"
)
print(
    json.dumps(
        {
            "tables_verified": len(before) - 1,
            "new_tables": sorted(set(after) - set(before)),
            "qualified_details": len(reading_after["qualified_details_verified"]),
        }
    )
)
