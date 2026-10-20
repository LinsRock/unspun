"""Read deployed files, rendered service graph and actual container roles only."""

import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path


def output(*command):
    return subprocess.check_output(command, text=True, timeout=30)


rows = json.loads(output("docker", "inspect", *output("docker", "ps", "-aq").split()))
containers = []
for row in rows:
    labels = row["Config"].get("Labels") or {}
    if labels.get("com.docker.compose.project") != "unspun":
        continue
    values = dict(v.split("=", 1) for v in row["Config"].get("Env", []) if "=" in v)
    containers.append(
        {
            "name": row["Name"].lstrip("/"),
            "service": labels.get("com.docker.compose.service"),
            "state": row["State"]["Status"],
            "image": row["Config"]["Image"],
            "image_id": row["Image"],
            "command": row["Config"]["Cmd"],
            "app_version": values.get("UNSPUN_APP_VERSION"),
            "ports": row["HostConfig"]["PortBindings"],
            "mounts": [
                {"type": m["Type"], "destination": m["Destination"], "name": m.get("Name")}
                for m in row["Mounts"]
            ],
        }
    )
api = next(c for c in containers if c["service"] == "api")
web = next(c for c in containers if c["service"] == "web")
folder = Path.home() / "unspun/deploy"
env = {
    **os.environ,
    "SERVER_IMAGE": api["image"],
    "WEB_IMAGE": web["image"],
    "APP_VERSION": api["app_version"],
}
config = json.loads(
    subprocess.check_output(
        [
            "docker",
            "compose",
            "--env-file",
            str(folder.parent / ".env"),
            "-f",
            str(folder / "compose.yml"),
            "-f",
            str(folder / "compose.prod.yml"),
            "config",
            "--format",
            "json",
        ],
        env=env,
        text=True,
        timeout=30,
    )
)
services = {
    name: {
        k: v[k]
        for k in ("image", "command", "scale", "restart", "ports", "mem_limit", "memswap_limit")
        if k in v
    }
    for name, v in config["services"].items()
}
print(
    json.dumps(
        {
            "checked_at": datetime.now(UTC).isoformat(),
            "files": {
                name: hashlib.sha256((folder / name).read_bytes()).hexdigest()
                for name in (
                    "compose.yml",
                    "compose.prod.yml",
                    "compose.local.yml",
                    "deploy.sh",
                    "env.example",
                    "Caddyfile",
                )
            },
            "services": services,
            "containers": containers,
            "legacy_all_states": sum(c["service"] == "worker" for c in containers),
            "controlled_running": sum(
                c["service"] == "r1-worker" and c["state"] == "running" for c in containers
            ),
            "controlled_enabled": config["services"]["r1-worker"]["environment"][
                "UNSPUN_R1_WORKER_ENABLED"
            ],
        },
        indent=2,
    )
)
