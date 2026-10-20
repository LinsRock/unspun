"""CL-00 Docker metadata only. Execute on each host; exports no env values/secrets.

Docker list/inspect/df and backup stat/pg_restore --list are read-only. No compose
up/run, migrations, initialization, prune, network/provider or worker command.
"""

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

mode = sys.argv[1]
assert mode in {"local", "production"}
out = {"environment": mode, "captured_at": datetime.now(UTC).isoformat(), "commands": []}


def run(*args):
    p = subprocess.run(args, capture_output=True, text=True, timeout=40, check=False)
    out["commands"].append({"argv": list(args), "exit_code": p.returncode})
    return p.stdout.strip()


def inspect(kind, identifier):
    return json.loads(run("docker", kind, "inspect", identifier))[0]


containers = []
for cid in run("docker", "ps", "-aq", "--no-trunc").splitlines():
    data = inspect("container", cid)
    labels = data["Config"].get("Labels") or {}
    owner = labels.get("com.docker.compose.project")
    if not (data["Name"].startswith("/unspun") or owner in {"unspun", "unspun-edge"}):
        containers.append(
            {
                "id": cid,
                "name": data["Name"],
                "owner": owner,
                "image": data["Config"]["Image"],
                "image_id": data["Image"],
                "state": data["State"]["Status"],
                "mounts": data["Mounts"],
                "disposition": "keep",
                "reason": "Other project; outside Unspun",
            }
        )
        continue
    containers.append(
        {
            "id": cid,
            "name": data["Name"],
            "image": data["Config"]["Image"],
            "image_id": data["Image"],
            "state": data["State"]["Status"],
            "restart": data["HostConfig"]["RestartPolicy"],
            "owner": owner,
            "role": labels.get("io.unspun.role"),
            "ports": data["HostConfig"]["PortBindings"],
            "mounts": data["Mounts"],
            "log": {"path": data.get("LogPath"), "config": data["HostConfig"]["LogConfig"]},
        }
    )
out["containers"] = containers
images = []
for iid in sorted(set(run("docker", "image", "ls", "-q", "--no-trunc").splitlines())):
    d = inspect("image", iid)
    images.append(
        {
            "id": iid,
            "tags": d.get("RepoTags"),
            "digests": d.get("RepoDigests"),
            "bytes": d["Size"],
            "created_at": d["Created"],
            "container_refs": [c["name"] for c in containers if c.get("image_id") == iid],
        }
    )
out["images"] = images
volumes = []
for name in run("docker", "volume", "ls", "-q").splitlines():
    d = inspect("volume", name)
    volumes.append(
        {
            "name": name,
            "mountpoint": d["Mountpoint"],
            "labels": d.get("Labels"),
            "container_refs": [
                c["name"]
                for c in containers
                if any(m.get("Name") == name for m in c.get("mounts", []))
            ],
        }
    )
out["volumes"] = volumes
out["networks"] = [
    json.loads(line)
    for line in run("docker", "network", "ls", "--format", "{{json .}}").splitlines()
]
out["disk_summary"] = run("docker", "system", "df")
out["volume_summary"] = run("docker", "system", "df", "-v")
out["builder_cache"] = run("docker", "builder", "du")
if mode == "local":
    # Other projects share this daemon. Keep their counts outside our candidate
    # list and avoid publishing their names, registries or mounts in this repo.
    excluded = [c for c in containers if c.get("reason") == "Other project; outside Unspun"]
    out["outside_project_containers"] = len(excluded)
    out["containers"] = [c for c in containers if c not in excluded]
    owned_images = [
        i
        for i in images
        if any(
            t.startswith(("unspun-", "pgvector/", "diygod/rsshub:")) for t in i.get("tags") or []
        )
    ]
    out["outside_project_images"] = len(images) - len(owned_images)
    out["images"] = owned_images
    out["volumes"] = [
        v
        for v in volumes
        if v["name"].startswith("unspun_")
        or not (v.get("labels") or {}).get("com.docker.compose.project")
    ]
    out["outside_project_volumes"] = len(volumes) - len(out["volumes"])
    out["networks"] = [n for n in out["networks"] if n["Name"].startswith("unspun")]
    out["volume_summary"] = "\n".join(
        line
        for line in out["volume_summary"].splitlines()
        if "unspun" in line or any(v["name"] in line for v in out["volumes"])
    )
if mode == "production":
    out["backup_files"] = run(
        "docker",
        "exec",
        "unspun-db-backup-1",
        "bash",
        "-c",
        "find /backups -maxdepth 1 -type f -name '*.dump' "
        "-printf '%f %s %TY-%Tm-%TdT%TH:%TM:%TS%Tz\\n'",
    )
    out["backup_toc_probe"] = run(
        "docker",
        "exec",
        "unspun-db-backup-1",
        "bash",
        "-c",
        "latest=$(find /backups -maxdepth 1 -name '*.dump' -type f | sort | tail -1); "
        'printf \'%s\\n\' "$latest"; pg_restore --list "$latest" | head -18',
    )
    out["db_allocated"] = run(
        "docker", "exec", "unspun-db-1", "du", "-sk", "/var/lib/postgresql/data"
    )
    out["backup_allocated"] = run("docker", "exec", "unspun-db-backup-1", "du", "-sk", "/backups")
    out["deployment_files"] = []
    for name in (
        "deploy/compose.yml",
        "deploy/compose.prod.yml",
        "deploy/deploy.sh",
        "deploy/Caddyfile",
    ):
        p = Path.home() / "unspun" / name
        if p.exists():
            out["deployment_files"].append(
                {
                    "path": str(p),
                    "bytes": p.stat().st_size,
                    "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                }
            )
    out["health"] = json.loads(run("curl", "-fsS", "http://127.0.0.1:8080/api/health"))
print(json.dumps(out, indent=2, ensure_ascii=True))
