import json
import subprocess
import urllib.request
from datetime import UTC, datetime

ids = subprocess.check_output(["docker", "ps", "-q"], text=True).split()
containers = []
for row in json.loads(subprocess.check_output(["docker", "inspect", *ids])):
    values = dict(value.split("=", 1) for value in row["Config"].get("Env", []) if "=" in value)
    containers.append(
        {
            "name": row["Name"].lstrip("/"),
            "image": row["Config"]["Image"],
            "image_id": row["Image"],
            "status": row["State"]["Status"],
            "started_at": row["State"]["StartedAt"],
            "restart_count": row["RestartCount"],
            "app_version": values.get("UNSPUN_APP_VERSION"),
            "published_ports": row["NetworkSettings"]["Ports"],
        }
    )
with urllib.request.urlopen("http://127.0.0.1:8080/api/health", timeout=15) as response:
    health = json.load(response)
api_code = """
import hashlib, json, sys
from pathlib import Path
import unspun
from sqlalchemy import text
from unspun.core.config import get_settings
from unspun.core.db import get_engine

settings = get_settings()
root = Path(unspun.__file__).parent
out = {
    "python": sys.executable,
    "unspun": str(root),
    "source_sha256": {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*.py"))
    },
    "config_sha256": {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(Path(settings.config_dir).glob("*.yml"))
    },
}
with get_engine().connect() as c, c.begin() as tx:
    c.execute(text("SET TRANSACTION READ ONLY"))
    out["read_only"] = c.scalar(text("SELECT current_setting('transaction_read_only')"))
    out["schema"] = c.scalar(text("SELECT version_num FROM alembic_version"))
    out["indexes"] = [
        dict(r)
        for r in c.execute(
            text(
                (
                    "SELECT indexname,indexdef FROM pg_indexes "
                    "WHERE indexname IN ('ix_articles_canonical_identity',"
                    "'ix_content_derivations_ready_card') ORDER BY indexname"
                )
            )
        ).mappings()
    ]
    tx.rollback()
print(json.dumps(out))
"""
api_metadata = json.loads(
    subprocess.check_output(
        ["docker", "exec", "-i", "unspun-api-1", "python", "-"], input=api_code, text=True
    )
)
print(
    json.dumps(
        {
            "checked_at": datetime.now(UTC).isoformat(),
            "mode": "read-only",
            "health": health,
            "api_metadata": api_metadata,
            "running_containers": containers,
            "legacy_workers": sum(c["name"] == "unspun-worker-1" for c in containers),
            "r1_workers": sum(c["name"] == "unspun-r1-worker-1" for c in containers),
        },
        indent=2,
    )
)
