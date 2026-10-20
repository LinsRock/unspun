"""Validate only fixed current/previous images against a retained isolated schema."""
import hashlib
import json
import subprocess
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

ROOT = Path(__file__).resolve().parents[3]
DATABASE = "unspun_r206_restored_v2_20261020"
engine = create_engine("postgresql+psycopg://unspun:unspun@localhost:5432/" + DATABASE)


def snapshot():
    with engine.connect() as conn, conn.begin():
        conn.execute(text("SET TRANSACTION READ ONLY"))
        result = {}
        for table in sorted(inspect(conn).get_table_names()):
            quoted = conn.dialect.identifier_preparer.quote(table)
            result[table] = dict(conn.execute(text(f"SELECT count(*) AS rows,md5(string_agg(to_jsonb(t)::text,'' ORDER BY to_jsonb(t)::text)) AS hash FROM {quoted} t")).mappings().one())
        return result


current = subprocess.check_output(["docker", "image", "inspect", "unspun-r206:validation", "--format", "{{.Id}}"], text=True).strip()
previous = "sha256:79629bff80cc18197516a922ea017015d90ae62e5b6a8e8368ce6151a37a97d3"
before = snapshot()
report = {"database": DATABASE, "current_image_id": current, "previous_image_id": previous, "cases": {}}
base = ["docker", "run", "--rm", "--network", "unspun_default", "-e", "UNSPUN_DATABASE_URL=postgresql+psycopg://unspun:unspun@db:5432/" + DATABASE]
for name, image in (("current_schema_000019", current), ("previous_schema_000018", previous)):
    run = subprocess.run([*base, image, "alembic", "upgrade", "head"], capture_output=True, text=True, timeout=30)
    report["cases"][name] = {"image": image, "exit_code": run.returncode, "stdout": run.stdout, "stderr": run.stderr}
    assert (run.returncode == 0) == (name == "current_schema_000019")
    assert snapshot() == before
probe = '''import hashlib,json
from pathlib import Path
from unspun.core.config import get_settings
from unspun.core.member_models import ContentVector,MemberJudgment
from unspun.pipeline.member_processing import MemberHandler
import unspun
base=Path(unspun.__file__).parent
print(json.dumps({"unspun":str(base),"member_processing_enabled":get_settings().r2_member_processing_enabled,"source_sha256":{str(p.relative_to(base)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(base.rglob("*.py"))}},indent=2))'''
report["current_imports"] = json.loads(subprocess.check_output([*base, current, "python", "-c", probe], text=True, timeout=30))
local = ROOT / "server/src/unspun"
assert report["current_imports"]["source_sha256"] == {str(p.relative_to(local)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(local.rglob("*.py"))}
assert report["current_imports"]["member_processing_enabled"] is False
report.update(all_rows_and_schema_preserved=True, downgrade_used=False, arbitrary_old_images_supported=False)
Path(__file__).with_name("fixed-image-compatibility.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps({"current":current,"all_rows_and_schema_preserved":True,"new_chain_enabled":False}))
