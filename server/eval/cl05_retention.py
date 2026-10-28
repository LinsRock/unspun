"""CL-05 preparation: bounded reads and reversible writes to newly created labs only.

No application settings, workers, billing helpers or network providers are imported.
This is deliberately outside the runtime image's entry points and scheduler.
"""

import argparse
import hashlib
import json
import os
import re
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

SCHEMA = "000021"
MAX_SCAN = 50
MAX_BATCH = 10
MAX_BYTES = 1024 * 1024
MIN_AGE = timedelta(days=30)
PREFIX = "unspun_cl05_lab_"


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def durable_write(path, value):
    """Never overwrite a recovery original, and make it durable before DB commit."""
    data = encoded(value)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    directory = os.open(Path(path).parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    if Path(path).read_bytes() != data:
        raise ValueError("recovery file readback mismatch")


def local_dsn(dsn):
    info = conninfo_to_dict(dsn)
    if info.get("host") != "127.0.0.1" or info.get("hostaddr", "127.0.0.1") != "127.0.0.1":
        raise ValueError("writes require an explicit IPv4 loopback connection")
    if any(key in info for key in ("service", "options")):
        raise ValueError("service/options overrides are not allowed for writes")
    return info


def identity(conn):
    row = conn.execute(
        "SELECT current_database(), oid, inet_server_addr()::text, inet_server_port(), "
        "shobj_description(oid, 'pg_database'), "
        "(SELECT system_identifier::text FROM pg_control_system()) "
        "FROM pg_database WHERE datname=current_database()"
    ).fetchone()
    return dict(zip(("database", "oid", "address", "port", "marker", "cluster"), row, strict=True))


def create_isolation(dsn, registry_path):
    """CREATE only: there is intentionally no register-existing or force option."""
    local_dsn(dsn)
    if Path(registry_path).exists():
        raise ValueError("registration already exists")
    name = PREFIX + uuid.uuid4().hex[:20]
    marker = "cl05-new-isolation:" + uuid.uuid4().hex
    with psycopg.connect(dsn, autocommit=True, connect_timeout=5) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(name)))
        conn.execute(
            sql.SQL("COMMENT ON DATABASE {} IS {}").format(
                sql.Identifier(name), sql.Literal(marker)
            )
        )
    lab_dsn = make_conninfo(dsn, dbname=name)
    with psycopg.connect(lab_dsn, connect_timeout=5) as conn:
        registration = {"identity": identity(conn), "schema": SCHEMA, "clearances": {}}
        assert not conn.execute("SELECT 1 FROM pg_tables WHERE schemaname='public'").fetchall()
    durable_write(registry_path, registration)
    return {"database": name, "registry": str(registry_path), "schema_to_migrate": SCHEMA}


def verify_isolation(conn, dsn, registration):
    info = local_dsn(dsn)
    expected = registration["identity"]
    if not re.fullmatch(PREFIX + "[0-9a-f]{20}", info.get("dbname", "")):
        raise ValueError("only newly provisioned CL-05 databases can be modified")
    if identity(conn) != expected or not expected["marker"].startswith("cl05-new-isolation:"):
        raise ValueError("database registration mismatch")
    if registration["schema"] != SCHEMA:
        raise ValueError("registration schema mismatch")


def write_target(dsn, registration):
    info = local_dsn(dsn)
    if not registration or not re.fullmatch(PREFIX + "[0-9a-f]{20}", info.get("dbname", "")):
        raise ValueError("only newly provisioned CL-05 databases can be modified")
    if info["dbname"] != registration["identity"]["database"]:
        raise ValueError("database registration mismatch")


def catalog(conn):
    if conn.execute("SELECT version_num FROM alembic_version").fetchall() != [(SCHEMA,)]:
        raise ValueError("unreviewed schema; no candidate can be cleared")
    if conn.execute(
        "SELECT 1 FROM pg_tables WHERE schemaname NOT IN ('public','information_schema') "
        "AND schemaname NOT LIKE 'pg_%' LIMIT 1"
    ).fetchone():
        raise ValueError("unreviewed user schema")
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
        )
    ]
    columns = conn.execute(
        "SELECT table_name,column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND data_type IN ('json','jsonb') "
        "ORDER BY table_name,column_name"
    ).fetchall()
    foreign_keys = conn.execute(
        "SELECT conname, conrelid::regclass::text, "
        "array_agg(a.attname ORDER BY k.n), array_agg(b.attname ORDER BY k.n) "
        "FROM pg_constraint c CROSS JOIN LATERAL unnest(c.conkey,c.confkey) "
        "WITH ORDINALITY k(child,parent,n) "
        "JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.child "
        "JOIN pg_attribute b ON b.attrelid=c.confrelid AND b.attnum=k.parent "
        "WHERE c.contype='f' AND c.confrelid='content_materials'::regclass "
        "GROUP BY conname,conrelid ORDER BY conname"
    ).fetchall()
    return tables, columns, foreign_keys


def reference_pattern(material):
    # Deliberately overprotect numeric IDs in any JSON key/value, including nested
    # evidence, arrays and serialized version references. False positives stay kept.
    tokens = {str(material["id"]), str(material["article_id"])}
    tokens.update(
        str(material[k])
        for k in ("input_fingerprint", "text_fingerprint", "response_fingerprint")
        if material[k]
    )
    return (
        r"(?<![[:alnum:]])(" + "|".join(re.escape(t) for t in sorted(tokens)) + r")(?![[:alnum:]])"
    )


def inspect_candidate(conn, material, columns, foreign_keys, cutoff, clearance):
    mid = material["id"]
    reasons = []
    references = []
    for name, table, child, parent in foreign_keys:
        condition = sql.SQL(" AND ").join(
            sql.SQL("t.{}=m.{}").format(sql.Identifier(c), sql.Identifier(p))
            for c, p in zip(child, parent, strict=True)
        )
        count = conn.execute(
            sql.SQL(
                "SELECT count(*) FROM {} t JOIN content_materials m ON {} WHERE m.id=%s"
            ).format(sql.Identifier(table), condition),
            (mid,),
        ).fetchone()[0]
        if count:
            references.append(
                {"kind": "foreign_key", "object": name, "table": table, "count": count}
            )
    pattern = reference_pattern(material)
    for table, column in columns:
        exclude_self = sql.SQL(" AND t.id<>%s") if table == "content_materials" else sql.SQL("")
        params = (pattern, mid) if table == "content_materials" else (pattern,)
        count = conn.execute(
            sql.SQL("SELECT count(*) FROM {} t WHERE {}::jsonb::text ~ %s{}").format(
                sql.Identifier(table), sql.Identifier(column), exclude_self
            ),
            params,
        ).fetchone()[0]
        if count:
            references.append(
                {"kind": "json_conservative", "table": table, "column": column, "count": count}
            )
    # A task may use article_id/object_key instead of a JSON material pointer.
    # Terminal tasks and real/unknown cost evidence are retained too.
    for table in ("pipeline_tasks", "billed_requests"):
        count = conn.execute(
            sql.SQL(
                "SELECT count(*) FROM {} WHERE article_id=%s OR object_key ~ %s "
                "OR input_fingerprint=%s"
                if table == "pipeline_tasks"
                else "SELECT count(*) FROM {} WHERE article_id=%s OR object_key ~ %s "
                "OR request_fingerprint=%s"
            ).format(sql.Identifier(table)),
            (material["article_id"], pattern, material["input_fingerprint"]),
        ).fetchone()[0]
        if count:
            references.append({"kind": "owner_or_fingerprint", "table": table, "count": count})
    if references:
        reasons.append("database_reference")
    if datetime.fromisoformat(material["retrieved_at"]) > cutoff:
        reasons.append("minimum_30_days")
    if (
        material["access_status"] != "ok"
        or material["scope"] == "none"
        or not material["paragraphs"]
    ):
        reasons.append("failure_or_empty_original")
    # Keep the current same-owner material, with every content/evidence field equal.
    # Only observation identity/time may differ, and their complete originals are archived.
    ignored = ["id", "input_fingerprint", "retrieved_at"]
    keeper = conn.execute(
        "SELECT k.id FROM articles a JOIN content_materials k ON k.id=a.current_material_id "
        "WHERE a.id=%s AND k.id<>%s AND "
        "to_jsonb(k)-%s::text[]=%s::jsonb-%s::text[]",
        (material["article_id"], mid, ignored, json.dumps(material), ignored),
    ).fetchone()
    if not keeper:
        reasons.append("no_equivalent_current_material")
    row_hash = digest(material)
    if not clearance or clearance.get("row_sha256") != row_hash or not clearance.get("basis"):
        reasons.append("external_frozen_or_failure_review_pending")
    return {
        "id": mid,
        "article_id": material["article_id"],
        "row_sha256": row_hash,
        "logical_json_bytes": len(encoded(material)),
        "keeper_id": keeper[0] if keeper else None,
        "references": references,
        "exclusions": reasons,
        "eligible": not reasons,
    }


def inventory(conn, *, ids=None, clearances=None, after_id=0):
    start = time.monotonic()
    _, columns, foreign_keys = catalog(conn)
    at = conn.execute("SELECT transaction_timestamp()").fetchone()[0]
    if ids is None:
        rows = conn.execute(
            "SELECT to_jsonb(m) FROM content_materials m JOIN articles a ON a.id=m.article_id "
            "WHERE a.current_material_id IS DISTINCT FROM m.id AND m.id>%s "
            "ORDER BY m.id LIMIT %s",
            (after_id, MAX_SCAN + 1),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT to_jsonb(m) FROM content_materials m WHERE id=ANY(%s) ORDER BY id", (ids,)
        ).fetchall()
    truncated = len(rows) > MAX_SCAN
    objects = []
    for (row,) in rows[:MAX_SCAN]:
        if time.monotonic() - start > 90:
            raise ValueError("inventory time bound exceeded; no partial approval")
        objects.append(
            inspect_candidate(
                conn,
                row,
                columns,
                foreign_keys,
                at - MIN_AGE,
                (clearances or {}).get(str(row["id"])),
            )
        )
    if truncated:
        for obj in objects:
            obj["eligible"] = False
            obj["exclusions"].append("scan_truncated")
    relation = conn.execute(
        "SELECT count(*),pg_relation_size('content_materials'),"
        "pg_table_size('content_materials'),pg_indexes_size('content_materials'),"
        "pg_total_relation_size('content_materials') FROM content_materials"
    ).fetchone()
    return {
        "at": at.isoformat(),
        "database": conn.info.dbname,
        "schema": SCHEMA,
        "transaction_read_only": conn.execute("SHOW transaction_read_only").fetchone()[0],
        "mode": "dry-run",
        "scope": "noncurrent materials" if ids is None else "explicit IDs",
        "scan_limit": MAX_SCAN,
        "after_id": after_id,
        "next_after_id": objects[-1]["id"] if truncated else None,
        "truncated": truncated,
        "json_columns_checked": [f"{t}.{c}" for t, c in columns],
        "material_foreign_keys_checked": [r[0] for r in foreign_keys],
        "material_relation": dict(
            zip(
                ("rows", "heap_bytes", "table_bytes", "index_bytes", "total_bytes"),
                relation,
                strict=True,
            )
        ),
        "objects": objects,
        "eligible_count": sum(o["eligible"] for o in objects),
        "candidate_logical_json_bytes": sum(o["logical_json_bytes"] for o in objects),
        "actual_released_bytes": None,
    }


def limits(conn, *, readonly):
    if readonly:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
    else:
        conn.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED, READ WRITE")
    conn.execute("SET LOCAL statement_timeout='5s'")
    conn.execute("SET LOCAL transaction_timeout='120s'")
    conn.execute("SET LOCAL lock_timeout='1s'")
    conn.execute("SET LOCAL idle_in_transaction_session_timeout='30s'")
    conn.execute("SET LOCAL search_path=public,pg_catalog")


def lock_lab(conn):
    tables, _, _ = catalog(conn)
    # FK row locks alone cannot fence JSON-only inserts. This lab-only lock also
    # serializes cleaners. READ COMMITTED ensures recheck sees writers that finish first.
    conn.execute(
        sql.SQL("LOCK TABLE {} IN SHARE ROW EXCLUSIVE MODE").format(
            sql.SQL(",").join(sql.Identifier(t) for t in tables)
        )
    )


def run(dsn, *, ids=None, registration=None, archive=None, apply=False, after_id=0):
    if type(after_id) is not int or after_id < 0 or (after_id and (ids or apply)):
        raise ValueError("after_id is only for nonnegative read-only inventory pagination")
    if ids is not None and (
        not ids
        or len(ids) > MAX_BATCH
        or len(set(ids)) != len(ids)
        or any(type(i) is not int or i <= 0 for i in ids)
    ):
        raise ValueError("explicit batch requires 1..10 unique positive IDs")
    if apply:
        write_target(dsn, registration)
        if not registration or not ids or not archive:
            raise ValueError("apply requires registration, IDs and an exclusive recovery path")
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        limits(conn, readonly=not apply)
        if apply:
            verify_isolation(conn, dsn, registration)
            lock_lab(conn)
        result = inventory(
            conn, ids=ids, clearances=(registration or {}).get("clearances"), after_id=after_id
        )
        if not apply:
            conn.rollback()
            return result
        objects = result["objects"]
        if any(not obj["eligible"] for obj in objects):
            raise ValueError("batch has protected objects; rerun dry-run for exclusions")
        rows = [
            r[0]
            for r in conn.execute(
                "SELECT to_jsonb(m) FROM content_materials m WHERE id=ANY(%s) ORDER BY id", (ids,)
            )
        ]
        if sum(len(encoded(row)) for row in rows) > MAX_BYTES:
            raise ValueError("batch exceeds 1 MiB logical JSON limit")
        if not rows:
            result.update(mode="apply-isolation", deleted_ids=[], archive=None)
            return result
        recovery = {"identity": registration["identity"], "schema": SCHEMA, "rows": rows}
        recovery["sha256"] = digest(recovery)
        durable_write(archive, recovery)
        deleted = conn.execute(
            "DELETE FROM content_materials WHERE id=ANY(%s) RETURNING id", (ids,)
        ).fetchall()
        if sorted(r[0] for r in deleted) != [obj["id"] for obj in objects]:
            raise ValueError("delete result mismatch")
        conn.commit()
        result.update(
            mode="apply-isolation", deleted_ids=[r[0] for r in deleted], archive=str(archive)
        )
        return result


def restore(dsn, registration, archive):
    write_target(dsn, registration)
    if Path(archive).stat().st_size > 2 * MAX_BYTES:
        raise ValueError("recovery file exceeds bound")
    saved = json.loads(Path(archive).read_text())
    expected_hash = saved.pop("sha256")
    if digest(saved) != expected_hash or saved["identity"] != registration["identity"]:
        raise ValueError("recovery checksum/identity mismatch")
    rows = saved["rows"]
    if sum(len(encoded(row)) for row in rows) > MAX_BYTES:
        raise ValueError("recovery rows exceed logical byte bound")
    if (
        saved["schema"] != SCHEMA
        or len(rows) > MAX_BATCH
        or len({r["id"] for r in rows}) != len(rows)
    ):
        raise ValueError("invalid recovery schema/batch")
    restored = []
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        limits(conn, readonly=False)
        verify_isolation(conn, dsn, registration)
        lock_lab(conn)
        for row in rows:
            existing = conn.execute(
                "SELECT to_jsonb(m) FROM content_materials m WHERE id=%s", (row["id"],)
            ).fetchone()
            if existing:
                if existing[0] != row:
                    raise ValueError("recovery collision; no overwrite allowed")
                continue
            conn.execute(
                "INSERT INTO content_materials SELECT * FROM "
                "jsonb_populate_record(NULL::content_materials,%s::jsonb)",
                (json.dumps(row),),
            )
            actual = conn.execute(
                "SELECT to_jsonb(m) FROM content_materials m WHERE id=%s", (row["id"],)
            ).fetchone()[0]
            if actual != row:
                raise ValueError("recovered row mismatch")
            restored.append(row["id"])
    return {"restored_ids": restored, "actual_released_bytes": None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--create-isolation", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--restore", action="store_true")
    parser.add_argument("--dsn-env", default="CL05_DATABASE_URL")
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--ids", type=int, nargs="+")
    parser.add_argument("--after-id", type=int, default=0)
    args = parser.parse_args()
    dsn = os.environ[args.dsn_env]
    if args.create_isolation:
        if not args.registry:
            parser.error("--create-isolation requires --registry")
        result = create_isolation(dsn, args.registry)
    else:
        registration = json.loads(args.registry.read_text()) if args.registry else None
        if args.restore:
            if not registration or not args.archive:
                parser.error("--restore requires --registry and --archive")
            result = restore(dsn, registration, args.archive)
        else:
            result = run(
                dsn,
                ids=args.ids,
                registration=registration,
                archive=args.archive,
                apply=args.apply,
                after_id=args.after_id,
            )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
