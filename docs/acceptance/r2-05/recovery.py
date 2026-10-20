"""One-off isolated migration/retained-data recovery rehearsal; all paid processing is mocked."""

import hashlib
import json
import os
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "server"))
from tests.test_content_feed import NOW, ready
from tests.test_topics import CONTRACT, DEFINITION, derive, member, update, write
from unspun.core.billing_models import BilledRequest, BudgetPolicy
from unspun.core.models import Article, Digest, Event, LlmUsage
from unspun.core.reader_models import ContentFeedback, ReaderInterest
from unspun.core.sources import load_sources
from unspun.core.tasks import enqueue
from unspun.core.topic_contracts import RemoveMember, RetractUpdate
from unspun.core.topics import read_topic

SOURCE = "unspun_r205_recovery_v2_20261020"
RESTORED = "unspun_r205_restored_v2_20261020"
PRIVATE = Path.home() / ".cache/unspun-r205-20261020"
PRIVATE.mkdir(parents=True, exist_ok=True)
output = {
    "source": SOURCE,
    "restored": RESTORED,
    "new_paid_requests": 0,
    "production_mutations": 0,
}


def url(database):
    assert database in (SOURCE, RESTORED)
    return "postgresql+psycopg://unspun:unspun@localhost:5432/" + database


def migrate(database, *arguments):
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=ROOT / "server",
        env=dict(os.environ, UNSPUN_DATABASE_URL=url(database)),
        capture_output=True,
        text=True,
        timeout=30,
    )
    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def snapshot(database):
    engine = create_engine(url(database))
    with engine.connect() as conn, conn.begin():
        conn.execute(text("SET TRANSACTION READ ONLY"))
        rows = {}
        for table in sorted(inspect(conn).get_table_names()):
            quoted = conn.dialect.identifier_preparer.quote(table)
            rows[table] = dict(
                conn.execute(
                    text(
                        f"SELECT count(*) AS rows,md5(string_agg(to_jsonb(t)::text,'' ORDER BY to_jsonb(t)::text)) AS hash FROM {quoted} t"
                    )
                )
                .mappings()
                .one()
            )
        sequences = list(
            conn.execute(
                text(
                    "SELECT sequencename,last_value FROM pg_sequences WHERE schemaname='public' ORDER BY sequencename"
                )
            ).mappings()
        )
    engine.dispose()
    return {"tables": rows, "sequences": [dict(row) for row in sequences]}


assert migrate(SOURCE, "upgrade", "000017")["returncode"] == 0
engine = create_engine(url(SOURCE))
topic = UUID("956b42c6-176a-4113-afd2-caf8acc4be86")
with Session(engine) as session, session.begin():
    assert session.scalar(text("SELECT count(*) FROM articles")) == 0
    legacy = Event(title="Retained synthetic historical event")
    session.add(legacy)
    session.flush()
    session.add(
        Article(
            source_id="synthetic-legacy",
            url="https://example.org/recovery-legacy",
            title="Historical pending article",
            event_id=legacy.id,
        )
    )
    first, second = ready(session), ready(session)
    first_id, second_id = first.id, second.id
    session.add(
        Digest(
            report_date=date(2026, 10, 19),
            payload={"intro": "Retained historical payload", "event_id": legacy.id},
        )
    )
    session.add(
        LlmUsage(purpose="summary", model="synthetic-no-provider-call", cost_usd=0.012)
    )
    session.add(
        BudgetPolicy(
            id=1,
            scope="evaluation",
            enabled=False,
            monthly_limit_usd=Decimal("1.5"),
            stage_caps={},
            version="synthetic-recovery-v1",
        )
    )
    session.add(
        BilledRequest(
            id="synthetic-unresolved",
            purpose="summary",
            stage="guide",
            phase="generation",
            model="synthetic-no-provider-call",
            request_fingerprint="synthetic",
            price_version="synthetic",
            reserved_usd=Decimal("0.05"),
            status="usage_unknown",
            article_id=first.id,
        )
    )
    session.add(
        ReaderInterest(
            resource_key="term:synthetic",
            kind="term",
            target={"kind": "term", "value": "synthetic"},
            label="Synthetic term",
        )
    )
    session.add(ContentFeedback(article_id=first.id, value="interested", version=1))
    enqueue(
        session,
        queue="material",
        kind="fetch_material",
        object_key="synthetic-recovery",
        article_id=first.id,
        input_fingerprint="synthetic",
        strategy_version="synthetic-v1",
        payload={"fixture": True},
    )
before = snapshot(SOURCE)
output["upgrade"] = migrate(SOURCE, "upgrade", "head")
assert output["upgrade"]["returncode"] == 0
after_upgrade = snapshot(SOURCE)
assert all(
    after_upgrade["tables"][k] == v
    for k, v in before["tables"].items()
    if k != "alembic_version"
)
assert after_upgrade["sequences"] == before["sequences"]
output["old_rows_unchanged_by_upgrade"] = True
source = next(s for s in load_sources() if s.id == "xinhua")
assert source.r1
sources = [
    source.model_copy(
        update={
            "legacy_enabled": False,
            "discovery_owner": "r1",
            "r1": source.r1.model_copy(
                update={"publish": True, "publish_scopes": None}
            ),
        }
    )
]
with Session(engine) as session, session.begin():
    first, second = session.get(Article, first_id), session.get(Article, second_id)
    assert first and second
    write(session, topic, DEFINITION, sources)
    write(session, topic, member(first), sources)
    write(session, topic, member(second, relation="background"), sources)
    progress = update(session, topic, first, sources)
    derive(session, topic, first, sources)
    update(
        session,
        topic,
        first,
        sources,
        update_id=progress.update_id,
        summary="Retained revised assertion",
    )
    write(session, topic, RetractUpdate(update_id=UUID(progress.update_id)), sources)
    write(session, topic, RemoveMember(article_id=first.id), sources)
    write(session, topic, member(first, relation="explanation"), sources)
    derive(session, topic, first, sources)
    original_view = read_topic(
        session, topic, sources=sources, now=NOW, contract=CONTRACT
    )
output["repeat_upgrade"] = migrate(SOURCE, "upgrade", "head")
assert output["repeat_upgrade"]["returncode"] == 0
full_before = snapshot(SOURCE)
output["downgrade"] = migrate(SOURCE, "downgrade", "000017")
assert output["downgrade"]["returncode"] != 0
assert snapshot(SOURCE) == full_before
output["downgrade_failed_closed_with_all_rows_retained"] = True
backup = PRIVATE / "retained-v2-schema-000018.dump"
with backup.open("xb") as handle:
    subprocess.run(
        [
            "docker",
            "exec",
            "unspun-db-1",
            "pg_dump",
            "-U",
            "unspun",
            "-d",
            SOURCE,
            "-Fc",
        ],
        stdout=handle,
        check=True,
        timeout=30,
    )
output["backup"] = {
    "path": str(backup),
    "bytes": backup.stat().st_size,
    "sha256": hashlib.sha256(backup.read_bytes()).hexdigest(),
}
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
            RESTORED,
            "--exit-on-error",
            "--no-owner",
        ],
        stdin=handle,
        check=True,
        timeout=30,
    )
output["restored_upgrade"] = migrate(RESTORED, "upgrade", "head")
assert output["restored_upgrade"]["returncode"] == 0
full_after = snapshot(RESTORED)
assert full_before == full_after
restored_engine = create_engine(url(RESTORED))
with Session(restored_engine) as session:
    restored_view = read_topic(
        session, topic, sources=sources, now=NOW, contract=CONTRACT
    )
assert original_view == restored_view
output.update(
    snapshot_before=full_before,
    snapshot_after=full_after,
    all_table_counts_hashes_and_sequences_match=True,
    internal_revision_and_validation_view_matches=True,
    retained_source_database=True,
    retained_restored_database=True,
)
Path(__file__).with_name("recovery-v2.json").write_text(
    json.dumps(output, default=str, ensure_ascii=False, indent=2) + "\n"
)
print(json.dumps({k: v for k, v in output.items() if isinstance(v, bool)}, indent=2))
