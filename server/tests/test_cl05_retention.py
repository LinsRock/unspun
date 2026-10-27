"""Real PostgreSQL cleanup tests; every write goes to a newly registered database."""

import importlib.util
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, LiteralString

import httpx
import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from tests.reading_fixtures import approve_event
from unspun.api.admin.auth import require_admin_identity
from unspun.api.app import app
from unspun.api.events import get_db, get_feed_now
from unspun.core.billing import budget_status
from unspun.core.config import get_settings
from unspun.core.models import Article, Event
from unspun.core.tasks import claim, enqueue

SCRIPT = Path(__file__).parents[1] / "eval/cl05_retention.py"
spec = importlib.util.spec_from_file_location("cl05_retention", SCRIPT)
assert spec and spec.loader
cleanup: Any = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleanup)
MID = 810001
AID = 910001


@dataclass
class Lab:
    dsn: str
    registration: dict[str, Any]
    path: Path

    def execute(self, query: LiteralString, params: tuple[Any, ...] = ()) -> None:
        with psycopg.connect(self.dsn) as conn:
            conn.execute(query, params)

    def scan(self) -> dict[str, Any]:
        return cleanup.run(self.dsn, ids=[MID], registration=self.registration)

    def apply(self, name: str = "recovery.json") -> dict[str, Any]:
        return cleanup.run(
            self.dsn,
            ids=[MID],
            registration=self.registration,
            archive=self.path / name,
            apply=True,
        )


@pytest.fixture
def lab(tmp_path: Path) -> Iterator[Lab]:
    url = make_url(get_settings().database_url).set(drivername="postgresql", host="127.0.0.1")
    maintenance = url.set(database="postgres").render_as_string(hide_password=False)
    try:
        with psycopg.connect(maintenance, connect_timeout=2):
            pass
    except psycopg.OperationalError:
        pytest.skip("local PostgreSQL required")
    registry = tmp_path / "registration.json"
    created = cleanup.create_isolation(maintenance, registry)
    dsn = make_conninfo(maintenance, dbname=created["database"])
    try:
        env = os.environ | {
            "UNSPUN_DATABASE_URL": url.set(
                drivername="postgresql+psycopg", database=created["database"]
            ).render_as_string(hide_password=False)
        }
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=SCRIPT.parents[1],
            env=env,
            check=True,
            capture_output=True,
        )
        result = Lab(dsn, json.loads(registry.read_text()), tmp_path)
        seed(result)
        yield result
    finally:
        # This database was created above, never selected from an existing list.
        with psycopg.connect(maintenance, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(created["database"])))


def seed(lab: Lab) -> None:
    with psycopg.connect(lab.dsn) as conn:
        conn.execute(
            "INSERT INTO articles(id,source_id,url,title,processing_track) "
            "VALUES (%s,'synthetic','https://example.invalid/material','Fixture','r1')",
            (AID,),
        )
        conn.execute(
            "INSERT INTO content_materials(id,article_id,input_fingerprint,text_fingerprint,"
            "metadata_fingerprint,extractor_version,schema_version,scope,access_status,completeness,"
            "completeness_basis,source_url,retrieved_at,paragraphs,evidence) "
            "SELECT n,%s,'input-'||n,'synthetic-text','synthetic-meta',"
            "'test','test','open_text_unit',"
            "'ok','observed_unit','synthetic','https://example.invalid/material',"
            'now()-interval \'31 days\',\'[{"id":"p1","text":"A synthetic original."}]\',\'{}\' '
            "FROM generate_series(%s,%s) n",
            (AID, MID, MID + 1),
        )
        conn.execute("UPDATE articles SET current_material_id=%s WHERE id=%s", (MID + 1, AID))
        row = conn.execute(
            "SELECT to_jsonb(m) FROM content_materials m WHERE id=%s", (MID,)
        ).fetchone()
        assert row
        lab.registration["clearances"][str(MID)] = {
            "row_sha256": cleanup.digest(row[0]),
            "basis": "Created by this synthetic test; no external/frozen/paid dependency",
        }


def hashes(lab: Lab) -> dict[str, str]:
    with psycopg.connect(lab.dsn) as conn:
        tables, _, _ = cleanup.catalog(conn)
        result: dict[str, str] = {}
        for table in tables:
            rows = conn.execute(
                sql.SQL("SELECT to_jsonb(t) FROM {} t").format(sql.Identifier(table))
            )
            result[table] = cleanup.digest(sorted(cleanup.digest(row[0]) for row in rows))
        return result


def test_default_is_readonly_and_recovery_is_exact_and_repeatable(lab: Lab) -> None:
    before = hashes(lab)
    dry = lab.scan()
    assert dry["transaction_read_only"] == "on"
    assert dry["eligible_count"] == 1
    assert hashes(lab) == before
    assert lab.apply()["deleted_ids"] == [MID]
    after = hashes(lab)
    assert {k: v for k, v in before.items() if k != "content_materials"} == {
        k: v for k, v in after.items() if k != "content_materials"
    }
    assert lab.apply("repeat.json")["deleted_ids"] == []
    assert lab.apply()["deleted_ids"] == []
    assert not (lab.path / "repeat.json").exists()
    assert cleanup.restore(lab.dsn, lab.registration, lab.path / "recovery.json")[
        "restored_ids"
    ] == [MID]
    assert hashes(lab) == before
    assert (
        cleanup.restore(lab.dsn, lab.registration, lab.path / "recovery.json")["restored_ids"] == []
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"input_snapshot": {"members": [{"material_id": MID}]}},
        {"evidence": [{"version": {"material": str(MID)}}]},
        {"versions": [MID]},
        {"source": "material:" + str(MID)},
        {"fingerprint": "input-" + str(MID)},
        {str(MID): "map-key"},
    ],
)
def test_json_reference_added_after_dry_run_is_protected(lab: Lab, payload: dict[str, Any]) -> None:
    assert lab.scan()["eligible_count"] == 1
    lab.execute(
        "INSERT INTO digests(report_date,payload) VALUES (current_date,%s::jsonb)",
        (json.dumps(payload),),
    )
    before = hashes(lab)
    assert lab.scan()["objects"][0]["references"]
    with pytest.raises(ValueError, match="protected"):
        lab.apply()
    assert hashes(lab) == before


@pytest.mark.parametrize(
    "status", ["pending", "running", "retry_wait", "budget_deferred", "completed", "failed"]
)
def test_tasks_including_terminal_receipts_protect_owner(lab: Lab, status: str) -> None:
    lab.execute(
        "INSERT INTO pipeline_tasks(queue,kind,object_key,article_id,input_fingerprint,"
        "strategy_version,dedupe_key,payload,status,due_at,lease_until) "
        "VALUES ('material','fetch','content:fixture',%s,'fixture','v1','receipt','{}',%s,now(),"
        "CASE WHEN %s='running' THEN now()+interval '1 minute' ELSE NULL END)",
        (AID, status, status),
    )
    before = hashes(lab)
    with pytest.raises(ValueError, match="protected"):
        lab.apply()
    assert hashes(lab) == before


def test_new_foreign_key_and_current_pointer_are_protected(lab: Lab) -> None:
    lab.execute("UPDATE articles SET current_material_id=%s WHERE id=%s", (MID, AID))
    refs = lab.scan()["objects"][0]["references"]
    assert any(ref.get("object") == "fk_articles_current_material" for ref in refs)
    with pytest.raises(ValueError, match="protected"):
        lab.apply()


def test_unique_failure_and_age_and_external_clearance_are_fail_closed(lab: Lab) -> None:
    lab.execute(
        "UPDATE content_materials SET access_status='failed',retrieved_at=now() WHERE id=%s", (MID,)
    )
    excluded = lab.scan()["objects"][0]["exclusions"]
    assert set(excluded) >= {
        "failure_or_empty_original",
        "minimum_30_days",
        "no_equivalent_current_material",
        "external_frozen_or_failure_review_pending",
    }
    with pytest.raises(ValueError, match="protected"):
        lab.apply()


@pytest.mark.parametrize(
    "target", ["unspun", "unspun_r210_preview_20261026", "unspun_quality_r1_20261016"]
)
def test_existing_databases_are_rejected(lab: Lab, target: str) -> None:
    # Rejection before connection also works when the target does not exist in CI.
    dsn = make_conninfo(lab.dsn, dbname=target)
    with pytest.raises(ValueError, match="newly provisioned"):
        cleanup.run(
            dsn,
            ids=[MID],
            registration=lab.registration,
            archive=lab.path / "forbidden.json",
            apply=True,
        )


def test_registration_oid_marker_and_schema_cannot_be_reused(lab: Lab) -> None:
    lab.registration["identity"]["oid"] += 1
    with pytest.raises(ValueError, match="registration mismatch"):
        lab.apply()


def test_partial_delete_failure_rolls_back_and_archive_remains(lab: Lab) -> None:
    before = hashes(lab)
    lab.execute(
        "CREATE FUNCTION cl05_fail_delete() RETURNS trigger LANGUAGE plpgsql AS "
        "'BEGIN RAISE EXCEPTION ''synthetic delete failure''; END'"
    )
    lab.execute(
        "CREATE TRIGGER cl05_fail AFTER DELETE ON content_materials "
        "FOR EACH ROW EXECUTE FUNCTION cl05_fail_delete()"
    )
    with pytest.raises(psycopg.errors.RaiseException, match="synthetic delete failure"):
        lab.apply()
    assert hashes(lab) == before
    assert (lab.path / "recovery.json").exists()
    assert (
        cleanup.restore(lab.dsn, lab.registration, lab.path / "recovery.json")["restored_ids"] == []
    )


def test_archive_failure_cannot_delete_and_restore_rejects_corruption(lab: Lab) -> None:
    before = hashes(lab)
    with pytest.raises(FileNotFoundError):
        lab.apply("absent/recovery.json")
    assert hashes(lab) == before
    lab.apply()
    path = lab.path / "recovery.json"
    original = path.read_bytes()
    path.write_bytes(original.replace(b"A synthetic original.", b"A corrupted original."))
    with pytest.raises(ValueError, match="checksum"):
        cleanup.restore(lab.dsn, lab.registration, path)
    path.write_bytes(original)
    cleanup.restore(lab.dsn, lab.registration, path)
    lab.execute("UPDATE content_materials SET source_excerpt='conflict' WHERE id=%s", (MID,))
    with pytest.raises(ValueError, match="collision"):
        cleanup.restore(lab.dsn, lab.registration, path)


def test_bounds_and_remote_writes_are_rejected(lab: Lab) -> None:
    with pytest.raises(ValueError, match="1..10"):
        cleanup.run(lab.dsn, ids=list(range(1, 12)))
    with pytest.raises(ValueError, match="1..10"):
        cleanup.run(lab.dsn, ids=[MID, MID])
    with pytest.raises(ValueError, match="loopback"):
        cleanup.run(make_conninfo(lab.dsn, host="production.invalid"), apply=True)


def test_lock_timeout_keeps_candidate_and_never_writes_archive(lab: Lab) -> None:
    with psycopg.connect(lab.dsn) as writer:
        writer.execute("UPDATE articles SET title='concurrent edit' WHERE id=%s", (AID,))
        with pytest.raises(psycopg.errors.LockNotAvailable):
            lab.apply()
        assert not (lab.path / "recovery.json").exists()
        writer.rollback()
    assert lab.scan()["eligible_count"] == 1


def seed_protected(lab: Lab) -> None:
    """Nonempty histories and accounting make unchanged-row assertions meaningful."""
    lab.execute(
        "INSERT INTO articles(id,source_id,url,title) "
        "VALUES (920001,'bbc-world','https://example.invalid/history','Historical')"
    )
    lab.execute(
        "INSERT INTO content_identities(article_id,namespace,external_id) "
        "VALUES (920001,'synthetic','canonical')"
    )
    lab.execute(
        "INSERT INTO content_urls(article_id,url,relation) "
        "VALUES (920001,'https://example.invalid/history','canonical')"
    )
    lab.execute("INSERT INTO reader_state(id,version) VALUES (1,2)")
    lab.execute(
        "INSERT INTO content_feedback(article_id,value,version) VALUES (920001,'interested',2)"
    )
    lab.execute(
        "INSERT INTO reader_changes(version,mutation_id,fingerprint,kind,target,value) "
        "VALUES (1,'original','fp','feedback','{\"article_id\":920001}',NULL)"
    )
    lab.execute(
        "INSERT INTO reader_requests(mutation_id,fingerprint,version,unchanged) "
        "VALUES ('noop','fp',2,true)"
    )
    lab.execute(
        "INSERT INTO discovery_batches(source_id,cycle_key,version,observed_at,quotas,"
        "counters,material_tasks,paid_outcomes) "
        "VALUES ('synthetic','original','v2',now(),'{\"material_limit\":4}',"
        "'{\"selected\":1}','[930001]','{\"unknown\":1}')"
    )
    lab.execute(
        "INSERT INTO pipeline_tasks(id,queue,kind,object_key,article_id,input_fingerprint,"
        "strategy_version,dedupe_key,payload,status,due_at,attempts,failures,last_error) "
        "VALUES (930001,'material','fetch','history',920001,'historic','v1','original',"
        "'{}','retry_wait',now()-interval '1 hour',1,1,'Original failure')"
    )
    lab.execute(
        "INSERT INTO task_attempts(id,task_id,claim_version,worker,started_at,lease_until,"
        "status,error) VALUES (940001,930001,0,'synthetic',now(),now(),'failed','Original')"
    )
    lab.execute(
        "INSERT INTO budget_policy(id,scope,enabled,monthly_limit_usd,stage_caps,version,"
        "coverage_started_at,incident) VALUES (1,'evaluation',false,1.5,'{}','synthetic',"
        "now()-interval '1 day','paid-stop')"
    )
    lab.execute(
        "INSERT INTO budget_carry(month,amount_usd,ledger_at_observation_usd,basis,observed_at) "
        "VALUES (date_trunc('month',now())::date,0.02,0,'synthetic',now())"
    )
    lab.execute(
        "INSERT INTO llm_usage(id,purpose,model,cost_usd) VALUES (950001,'card','synthetic',0.0125)"
    )
    lab.execute(
        "INSERT INTO billed_requests(id,purpose,stage,phase,model,request_fingerprint,"
        "price_version,reserved_usd,status,article_id,task_id,task_attempt_id,usage_id,error) "
        "VALUES ('unknown','card','card','generation','synthetic','original','v1',0.08,"
        "'usage_unknown',920001,930001,940001,NULL,'Original unknown'),"
        "('known','card','card','generation','synthetic','known','v1',0.03,"
        "'responded',920001,930001,940001,950001,NULL)"
    )
    lab.execute(
        "INSERT INTO digests(report_date,payload) "
        'VALUES (current_date,\'{"original":true,"rating":null}\')'
    )


@pytest.mark.anyio
async def test_reading_identity_feedback_recovery_quota_and_cost_semantics(lab: Lab) -> None:
    seed_protected(lab)
    params = conninfo_to_dict(lab.dsn)
    url = make_url(get_settings().database_url).set(
        host="127.0.0.1", database=str(params["dbname"])
    )
    engine = create_engine(url)
    now = datetime.now(UTC)
    with Session(engine) as session:
        event = Event(
            title="Historical event",
            score_final=50,
            changed_at=now,
            first_seen_at=now - timedelta(hours=1),
        )
        session.add(event)
        session.flush()
        article = session.get(Article, 920001)
        assert article
        article.fetched_at = now - timedelta(hours=2)
        article.event = event
        session.flush()
        approve_event(event)
        # This also exercises a canonical, durable dedupe key rather than a row count.
        dedupe_id = enqueue(
            session,
            queue="guide",
            kind="historical_guide",
            object_key="history",
            input_fingerprint="historic",
            strategy_version="v1",
            payload={},
            article_id=920001,
            due_at=now + timedelta(days=1),
        )
        session.commit()

    def db() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_feed_now] = lambda: now
    app.dependency_overrides[require_admin_identity] = lambda: "synthetic-test"
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/events?range=all")
            assert response.status_code == 200
            before_read = response.json()
            assert before_read["events"]
            with Session(engine) as session:
                before_cost = budget_status(session)
            assert before_cost["unresolved_calls"] == 1
            assert Decimal(before_cost["reserved_usd"]) == Decimal("0.08")
            assert Decimal(before_cost["accounting"]["known_spend_usd"]) == Decimal("0.0125")
            before = hashes(lab)
            lab.apply()
            assert (await client.get("/api/events?range=all")).json() == before_read
            with Session(engine) as session:
                assert budget_status(session) == before_cost
                assert (
                    enqueue(
                        session,
                        queue="guide",
                        kind="historical_guide",
                        object_key="history",
                        input_fingerprint="historic",
                        strategy_version="v1",
                        payload={},
                        article_id=920001,
                    )
                    == dedupe_id
                )
                lease = claim(
                    session,
                    queue="material",
                    kinds={"fetch"},
                    worker="synthetic",
                    task_ids=frozenset({930001}),
                )
                assert lease and lease.task_id == 930001
                session.rollback()
            after = hashes(lab)
            assert all(after[k] == v for k, v in before.items() if k != "content_materials")
            cleanup.restore(lab.dsn, lab.registration, lab.path / "recovery.json")
            assert hashes(lab) == before
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def another_candidate(lab: Lab) -> None:
    with psycopg.connect(lab.dsn) as conn:
        row = conn.execute(
            "SELECT to_jsonb(m) FROM content_materials m WHERE id=%s", (MID,)
        ).fetchone()
        assert row
        extra = row[0] | {"id": MID + 2, "input_fingerprint": "input-extra"}
        conn.execute(
            "INSERT INTO content_materials SELECT * FROM "
            "jsonb_populate_record(NULL::content_materials,%s::jsonb)",
            (json.dumps(extra),),
        )
        lab.registration["clearances"][str(MID + 2)] = {
            "row_sha256": cleanup.digest(extra),
            "basis": "Synthetic local original",
        }


def test_restore_conflict_rolls_back_preceding_row(lab: Lab) -> None:
    another_candidate(lab)
    archive = lab.path / "two-rows.json"
    cleanup.run(
        lab.dsn, ids=[MID, MID + 2], registration=lab.registration, archive=archive, apply=True
    )
    saved = json.loads(archive.read_text())
    changed = saved["rows"][1] | {"source_excerpt": "new state"}
    lab.execute(
        "INSERT INTO content_materials SELECT * FROM "
        "jsonb_populate_record(NULL::content_materials,%s::jsonb)",
        (json.dumps(changed),),
    )
    before = hashes(lab)
    with pytest.raises(ValueError, match="collision"):
        cleanup.restore(lab.dsn, lab.registration, archive)
    assert hashes(lab) == before


def test_total_byte_bound_and_unreviewed_schema_fail_closed(lab: Lab) -> None:
    lab.execute("UPDATE content_materials SET source_excerpt=%s", ("x" * 600_000,))
    another_candidate(lab)
    with psycopg.connect(lab.dsn) as conn:
        row = conn.execute(
            "SELECT to_jsonb(m) FROM content_materials m WHERE id=%s", (MID,)
        ).fetchone()
        assert row
        lab.registration["clearances"][str(MID)]["row_sha256"] = cleanup.digest(row[0])
    before = hashes(lab)
    with pytest.raises(ValueError, match="1 MiB"):
        cleanup.run(
            lab.dsn,
            ids=[MID, MID + 2],
            registration=lab.registration,
            archive=lab.path / "oversize.json",
            apply=True,
        )
    assert not (lab.path / "oversize.json").exists()
    assert hashes(lab) == before
    lab.execute("UPDATE alembic_version SET version_num='000022'")
    with pytest.raises(ValueError, match="unreviewed schema"):
        lab.scan()


def test_bounded_inventory_marks_truncation_and_requires_explicit_page(lab: Lab) -> None:
    with psycopg.connect(lab.dsn) as conn:
        row = conn.execute(
            "SELECT to_jsonb(m) FROM content_materials m WHERE id=%s", (MID,)
        ).fetchone()
        assert row
        for offset in range(2, 53):
            extra = row[0] | {"id": MID + offset, "input_fingerprint": f"input-extra-{offset}"}
            conn.execute(
                "INSERT INTO content_materials SELECT * FROM "
                "jsonb_populate_record(NULL::content_materials,%s::jsonb)",
                (json.dumps(extra),),
            )
    first = cleanup.run(lab.dsn, registration=lab.registration)
    assert first["truncated"] and len(first["objects"]) == 50 and first["eligible_count"] == 0
    assert first["next_after_id"] == MID + 50
    second = cleanup.run(lab.dsn, after_id=first["next_after_id"])
    assert not second["truncated"] and len(second["objects"]) == 2
