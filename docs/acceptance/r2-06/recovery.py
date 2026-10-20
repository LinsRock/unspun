"""One-off additive migration and full restore rehearsal with mocked member processing."""

import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "server"))
from tests.test_billing import BillingDB
from tests.test_content_feed import ready
from tests.test_member_processing import MemberDB
from tests.test_topics import DEFINITION, member, write
from unspun.core.billing import DatabaseJournal, TOPIC_STAGE_CAPS, month_start
from unspun.core.billing_models import BilledRequest, BudgetCarry, BudgetPolicy
from unspun.core.config import get_settings
from unspun.core.content import fingerprint
from unspun.core.member_models import ContentVector, MemberJudgment
from unspun.core.models import Article, Digest, Event, LlmUsage
from unspun.core.sources import load_sources
from unspun.core.topic_contracts import RemoveMember
from unspun.core.topics import read_topic
from tests.test_topics import CONTRACT

SOURCE = "unspun_r206_recovery_v2_20261020"
RESTORED = "unspun_r206_restored_v2_20261020"
PRIVATE = Path.home() / ".cache/unspun-r206-20261020"
PRIVATE.mkdir(parents=True, exist_ok=True)
report = {"source": SOURCE, "restored": RESTORED, "new_paid_requests": 0, "production_mutations": 0}
os.environ["UNSPUN_CONFIG_DIR"] = str(ROOT / "config")
os.environ["UNSPUN_OPENROUTER_API_KEY"] = "synthetic-recovery-key"
os.environ["UNSPUN_R2_MEMBER_PROCESSING_ENABLED"] = "true"
get_settings.cache_clear()


def url(database):
    assert database in (SOURCE, RESTORED)
    return "postgresql+psycopg://unspun:unspun@localhost:5432/" + database


def migrate(database, *args):
    result = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=ROOT / "server", env=dict(os.environ, UNSPUN_DATABASE_URL=url(database)), capture_output=True, text=True, timeout=30)
    return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def snapshot(database):
    engine = create_engine(url(database))
    with engine.connect() as conn, conn.begin():
        conn.execute(text("SET TRANSACTION READ ONLY"))
        tables = {}
        for table in sorted(inspect(conn).get_table_names()):
            quoted = conn.dialect.identifier_preparer.quote(table)
            tables[table] = dict(conn.execute(text(f"SELECT count(*) AS rows,md5(string_agg(to_jsonb(t)::text,'' ORDER BY to_jsonb(t)::text)) AS hash FROM {quoted} t")).mappings().one())
        sequences = [dict(r) for r in conn.execute(text("SELECT sequencename,last_value FROM pg_sequences WHERE schemaname='public' ORDER BY sequencename")).mappings()]
    engine.dispose()
    return {"tables": tables, "sequences": sequences}


for database in (SOURCE, RESTORED):
    subprocess.run(["docker", "exec", "unspun-db-1", "createdb", "-U", "unspun", database], check=True)
assert migrate(SOURCE, "upgrade", "000018")["returncode"] == 0
engine = create_engine(url(SOURCE))
source = next(s for s in load_sources() if s.id == "xinhua")
assert source.r1
sources = [source.model_copy(update={"discovery_owner": "r1", "legacy_enabled": False, "r1": source.r1.model_copy(update={"paid": True, "publish": True, "paid_scopes": None, "publish_scopes": None})})]
topic = uuid4()
now = datetime.now(UTC)
with Session(engine) as session, session.begin():
    legacy = Event(title="Retained synthetic event")
    session.add(legacy)
    session.flush()
    session.add(Article(title="Retained pending legacy", url="https://example.org/r206-recovery", source_id="synthetic", event_id=legacy.id))
    session.add(Digest(report_date=now.date(), payload={"retained": True}))
    article, anchor = ready(session), ready(session)
    article_id, anchor_id = article.id, anchor.id
    write(session, topic, DEFINITION, sources)
    write(session, topic, member(anchor), sources)
    session.add(LlmUsage(purpose="summary", model="synthetic-no-provider", cost_usd=0.012))
    session.add(BudgetPolicy(id=1, scope="evaluation", enabled=True, monthly_limit_usd=Decimal("1.50"), stage_caps=TOPIC_STAGE_CAPS, version="synthetic-recovery", coverage_started_at=now, key_fingerprint=hashlib.sha256(b"synthetic-recovery-key").hexdigest()))
    session.add(BudgetCarry(month=month_start(now).date(), amount_usd=Decimal(0), ledger_at_observation_usd=Decimal(0), basis="synthetic-recovery", observed_at=now))
    session.add(BilledRequest(id="synthetic-retained-unknown", purpose="summary", stage="guide", phase="generation", model="synthetic-no-provider", request_fingerprint="retained", price_version="synthetic", reserved_usd=Decimal("0.05"), status="usage_unknown", article_id=anchor.id))
before = snapshot(SOURCE)
report["upgrade"] = migrate(SOURCE, "upgrade", "head")
assert report["upgrade"]["returncode"] == 0
upgraded = snapshot(SOURCE)
assert all(upgraded["tables"][k] == v for k, v in before["tables"].items() if k != "alembic_version")
assert upgraded["sequences"] == before["sequences"]
report["old_rows_and_sequences_unchanged_by_upgrade"] = True
mocked = MemberDB(BillingDB(engine, DatabaseJournal(engine)), sources, article_id, anchor_id, topic)
mocked.enqueue()
mocked.step("topic_recall")
mocked.step("topic_judge")
mocked.step("topic_review")
assert mocked.judgment().status == "applied"
with Session(engine) as session, session.begin():
    write(session, topic, RemoveMember(article_id=article_id), sources)
    view = read_topic(session, topic, sources=sources, now=datetime.now(UTC), contract=CONTRACT)
report["repeat_upgrade"] = migrate(SOURCE, "upgrade", "head")
assert report["repeat_upgrade"]["returncode"] == 0
full = snapshot(SOURCE)
report["downgrade"] = migrate(SOURCE, "downgrade", "000018")
assert report["downgrade"]["returncode"] != 0 and snapshot(SOURCE) == full
backup = PRIVATE / "retained-schema-000019.dump"
with backup.open("xb") as handle:
    subprocess.run(["docker", "exec", "unspun-db-1", "pg_dump", "-U", "unspun", "-d", SOURCE, "-Fc"], stdout=handle, check=True, timeout=30)
with backup.open("rb") as handle:
    subprocess.run(["docker", "exec", "-i", "unspun-db-1", "pg_restore", "-U", "unspun", "-d", RESTORED, "--exit-on-error", "--no-owner"], stdin=handle, check=True, timeout=30)
assert migrate(RESTORED, "upgrade", "head")["returncode"] == 0
restored = snapshot(RESTORED)
assert full == restored
restored_engine = create_engine(url(RESTORED))
with Session(restored_engine) as session:
    # Compare with the original exact validation time so no synthetic time is manufactured.
    restored_view = read_topic(session, topic, sources=sources, now=datetime.now(UTC), contract=CONTRACT)
    assert restored_view == view
    vector = session.query(ContentVector).first()
    judgment = session.query(MemberJudgment).one()
    assert vector and fingerprint(vector.input_snapshot) == vector.input_fingerprint
    assert judgment.status == "applied" and judgment.review["approved"]
    unknown = session.get(BilledRequest, "synthetic-retained-unknown")
    assert unknown and unknown.status == "usage_unknown" and unknown.reserved_usd == Decimal("0.05")
report.update(backup={"path": str(backup), "bytes": backup.stat().st_size, "sha256": hashlib.sha256(backup.read_bytes()).hexdigest()}, before=before, after_upgrade=upgraded, full_before=full, full_after=restored, all_table_hashes_counts_sequences_match=True, topic_history_and_new_versions_match=True, unknown_hold_preserved=True, downgrade_failed_closed=True, retained_source_and_restored_databases=True, mock_physical_requests=len(mocked.calls))
Path(__file__).with_name("recovery.json").write_text(json.dumps(report, default=str, indent=2) + "\n")
print(json.dumps({k: v for k, v in report.items() if isinstance(v, bool)}, indent=2))
