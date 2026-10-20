"""Read-only R2-05 evidence, reusing prior probes without restarting observers."""

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("phase", choices=("predeploy", "postdeploy"))
args = parser.parse_args()
output = Path(__file__).parent


def capture(name, command, script, env=None):
    target = output / f"{args.phase}-{name}.json"
    if target.exists():
        print("Retained existing", target.name, flush=True)
        return
    result = subprocess.run(
        command,
        input=script,
        text=True,
        capture_output=True,
        check=True,
        timeout=60,
        env=env,
    )
    data = json.loads(result.stdout)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print(target.name, hashlib.sha256(target.read_bytes()).hexdigest(), flush=True)


remote_python = ["ssh", "unspun", "python3", "-"]
api_python = ["ssh", "unspun", "docker exec -i unspun-api-1 python -"]
for name, script in (
    ("runtime", "docs/acceptance/r2-03/deployment-probe.py"),
    ("reading", "docs/acceptance/r2-04/reading.py"),
    ("protected-production", "docs/acceptance/cl-01/protected-audit.py"),
    ("boundaries", "docs/acceptance/cl-01/runtime-boundaries.py"),
):
    command = (
        remote_python
        if name == "runtime"
        else ["ssh", "unspun", "docker exec -i unspun-r1-worker-1 python -"]
        if name == "boundaries"
        else api_python
    )
    capture(name, command, (ROOT / script).read_text())
capture(
    "production",
    ["ssh", "unspun", "docker exec -i unspun-r1-worker-1 python - production"],
    (ROOT / "docs/acceptance/r2-04/snapshot.py").read_text(),
)
environment = dict(
    os.environ,
    UNSPUN_DATABASE_URL="postgresql+psycopg://unspun:unspun@localhost:5432/unspun_quality_r1_20261016",
)
capture(
    "evaluation",
    [str(ROOT / "server/.venv/bin/python"), "-", "evaluation"],
    (ROOT / "docs/acceptance/r2-04/snapshot.py").read_text(),
    env=environment,
)
capture(
    "observation",
    remote_python,
    """
import hashlib, json, subprocess
from datetime import UTC, datetime
from pathlib import Path
ids = subprocess.check_output(["docker", "ps", "-aq"], text=True).split()
rows = json.loads(subprocess.check_output(["docker", "inspect", *ids]))
out = {"captured_at": datetime.now(UTC).isoformat(), "containers": []}
for row in rows:
    if "r204" not in row["Name"]:
        continue
    out["containers"].append({"id": row["Id"], "name": row["Name"], "image": row["Image"], "status": row["State"]["Status"], "started_at": row["State"]["StartedAt"], "restart_count": row["RestartCount"], "mounts": [{"source": m["Source"], "destination": m["Destination"], "rw": m["RW"]} for m in row["Mounts"]]})
base = Path("/home/leon/unspun-observations")
out["retained_files"] = {str(p.relative_to(base)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(base.rglob("*")) if p.is_file() and "r2-04" in str(p) and p.suffix not in (".log", ".tmp")}
print(json.dumps(out, indent=2))
""",
)
