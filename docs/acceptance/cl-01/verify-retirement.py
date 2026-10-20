"""One-off CL-01 real Docker checks on new projects/volumes, with mocked HTTP.

Uses the retired-service deployment files for every image, including rollback.
Only test containers are stopped; no existing DB/image/worktree is deleted.
Run at the worktree root with server/.venv/bin/python and --work-dir outside Git.
"""

import argparse
import json
import os
import shutil
import signal
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import yaml

ROOT = Path.cwd()
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--work-dir", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument(
    "--modes",
    nargs="+",
    default=[
        "base",
        "local",
        "production",
        "migration-failure",
        "interrupt",
        "budget-failure",
        "preflight-failure",
        "health-failure",
    ],
)
parser.add_argument(
    "--web-image", default="ghcr.io/linsrock/unspun-web:8dd144bc6cf5775e5dfe881cbdc50472bedb6486"
)
args = parser.parse_args()
WORK = args.work_dir.resolve()
WORK.mkdir(exist_ok=False, parents=True)
OUT = {"started_at": datetime.now(UTC).isoformat(), "cases": [], "paid_calls": 0}
CURRENT = "unspun-server:cl01-isolated"
ROLLBACK = "ghcr.io/linsrock/unspun-server:6f4fe4ff38c0b109f5d4648cddda0d4ae476fb93"
OLDER = "ghcr.io/linsrock/unspun-server:43150075d33e17298a21bfa909fac578f5d511d9"
WEB = args.web_image
PREFIX = "unspun-cl01-" + uuid.uuid4().hex[:8]


def run(command, env=None, check=True, timeout=180):
    p = subprocess.run(
        command, env=env, text=True, capture_output=True, timeout=timeout, check=False
    )
    if check and p.returncode:
        raise AssertionError(f"{command}: {p.returncode}\n{p.stdout}\n{p.stderr}")
    return p


def save():
    OUT["updated_at"] = datetime.now(UTC).isoformat()
    args.output.write_text(json.dumps(OUT, indent=2) + "\n")


for index, mode in enumerate(
    (
        "base",
        "local",
        "production",
        "migration-failure",
        "interrupt",
        "budget-failure",
        "preflight-failure",
        "health-failure",
    )
):
    if mode not in args.modes:
        continue
    folder = WORK / mode
    folder.mkdir()
    config = folder / "config"
    shutil.copytree(ROOT / "config", config)
    fixture = {
        "id": "cl01-mock",
        "name": "CL-01 isolated mock",
        "url": "https://cl01.example/feed",
        "weight": 1,
        "region": "intl",
        "kind": "official",
        "lang": "en",
        "legacy_enabled": False,
        "discovery_owner": "r1",
        "r1": {
            "discovery": True,
            "material": False,
            "paid": True,
            "period_seconds": 3600,
        },
    }
    (config / "sources.yml").write_text(yaml.safe_dump({"sources": [fixture]}))
    shutil.copy(ROOT / "docs/acceptance/cl-01/mock-http.py", folder / "sitecustomize.py")
    for name in ("compose.yml", "compose.prod.yml", "compose.local.yml", "deploy.sh"):
        shutil.copy(ROOT / "deploy" / name, folder / name)
    port = 18131 + index
    local = (folder / "compose.local.yml").read_text()
    for old, new in (
        (5432, 15531 + index),
        (8000, 18231 + index),
        (8080, port),
        (1200, 18331 + index),
    ):
        local = local.replace(f"127.0.0.1:{old}:", f"127.0.0.1:{new}:")
    (folder / "compose.local.yml").write_text(local)
    prod = (
        (folder / "compose.prod.yml")
        .read_text()
        .replace("127.0.0.1:8080:80", f"127.0.0.1:{port}:80")
    )
    mounts = [
        f"{config}:/app/config:ro",
        f"{folder / 'sitecustomize.py'}:/fixtures/sitecustomize.py:ro",
    ]
    # Insert only isolation fixtures into copied deployment files; repository files stay intact.
    base = yaml.safe_load((folder / "compose.yml").read_text())
    for service in ("api", "r1-worker"):
        base["services"][service]["volumes"] = list(mounts)
        base["services"][service]["environment"].update(
            {
                "PYTHONPATH": "/fixtures",
                "UNSPUN_CONFIG_DIR": "/app/config",
                "CL01_FAIL_BUDGET": "1" if mode == "budget-failure" else "0",
                "CL01_FAIL_CHECK": "1" if mode == "preflight-failure" else "0",
            }
        )
    if mode == "health-failure":
        base["services"]["api"]["environment"]["UNSPUN_APP_VERSION"] = "stale-isolated-version"
    (folder / "compose.yml").write_text(yaml.safe_dump(base, sort_keys=False))
    (folder / "compose.prod.yml").write_text(prod)
    envfile = folder / ".env"
    envfile.write_text(
        "POSTGRES_PASSWORD=unspun\nOPENROUTER_API_KEY=cl01-fake-no-provider-access\n"
    )
    env = {
        **os.environ,
        "OPENROUTER_API_KEY": "cl01-fake-no-provider-access",
        "POSTGRES_PASSWORD": "unspun",
        "SERVER_IMAGE": CURRENT,
        "WEB_IMAGE": WEB,
        "APP_VERSION": "cl01-isolated",
        "COMPOSE_PROJECT_NAME": f"{PREFIX}-{mode}",
        "UNSPUN_DEPLOY_ENV_FILE": str(envfile),
        "UNSPUN_DEPLOY_HEALTH_URL": f"http://127.0.0.1:{port}/api/health",
    }
    compose = [
        "docker",
        "compose",
        "--env-file",
        str(envfile),
        "-f",
        str(folder / "compose.yml"),
    ]
    if mode != "base":
        compose += [
            "-f",
            str(folder / ("compose.local.yml" if mode == "local" else "compose.prod.yml")),
        ]
    case = {"mode": mode, "project": env["COMPOSE_PROJECT_NAME"], "port": port}
    OUT["cases"].append(case)
    proc = None

    def sql(query, command=compose, environ=env):
        return run(
            command
            + [
                "exec",
                "-T",
                "db",
                "psql",
                "-U",
                "unspun",
                "-d",
                "unspun",
                "-Atc",
                query,
            ],
            environ,
        ).stdout.strip()

    def state(command=compose, environ=env):
        raw = run(command + ["ps", "--all", "--format", "json"], environ).stdout.strip()
        rows = (
            json.loads(raw or "[]")
            if raw.startswith("[") or not raw
            else [json.loads(line) for line in raw.splitlines()]
        )
        if isinstance(rows, dict):
            rows = [rows]
        return {r["Service"]: {"state": r["State"], "image": r["Image"]} for r in rows}

    def healthy(command=compose, environ=env):
        for _ in range(30):
            p = run(
                command
                + [
                    "exec",
                    "-T",
                    "api",
                    "python",
                    "-c",
                    'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8000/api/health").read().decode())',
                ],
                environ,
                check=False,
            )
            if p.returncode == 0:
                h = json.loads(p.stdout)
                assert h["version"] == environ["APP_VERSION"] and h["database"] == "ok"
                return h
            time.sleep(1)
        raise AssertionError("API did not become healthy")

    try:
        rendered = json.loads(run(compose + ["config", "--format", "json"], env).stdout)
        case["rendered_services"] = sorted(rendered["services"])
        assert "worker" not in rendered["services"]
        run(compose + ["up", "-d", "--wait", "--wait-timeout", "120", "db"], env)
        run(
            compose + ["run", "-T", "--rm", "--no-deps", "api", "alembic", "upgrade", "head"],
            env,
        )
        assert sql("SELECT version_num FROM alembic_version") == "000017"
        fixture_check = run(
            compose
            + [
                "run",
                "-T",
                "--rm",
                "--no-deps",
                "api",
                "python",
                "-c",
                "import sitecustomize; from pathlib import Path; "
                "assert Path('/app/config/sources.yml').is_file(); print(sitecustomize.__file__)",
            ],
            env,
        )
        assert "/fixtures/sitecustomize.py" in fixture_check.stdout
        case["http_fixture_imported"] = True
        if mode in ("base", "local"):
            run(
                compose + ["up", "-d", "--no-build", "--pull", "never", "--remove-orphans"],
                env,
            )
            case["health"] = healthy()
            case["services"] = state()
            assert "worker" not in case["services"] and "r1-worker" not in case["services"]
            run(compose + ["stop"], env)
            run(
                compose + ["up", "-d", "--no-build", "--pull", "never", "--remove-orphans"],
                env,
            )
            run(compose + ["restart", "api", "web"], env)
            case["health_after_restart"] = healthy()
        else:
            if mode in ("migration-failure", "interrupt"):
                fault = folder / "20261020_cl01_fault.py"
                fault.write_text(
                    'from alembic import op\nrevision="cl01_fault"\ndown_revision="000017"\n'
                    "branch_labels=None\ndepends_on=None\ndef upgrade():\n"
                    '    op.execute("CREATE TABLE cl01_fault_marker (id integer)")\n'
                    + (
                        '    raise RuntimeError("isolated migration failure")\n'
                        if mode == "migration-failure"
                        else '    op.execute("SELECT pg_sleep(120)")\n'
                    )
                    + "def downgrade():\n    pass\n"
                )
                base["services"]["api"]["volumes"].append(
                    f"{fault}:/app/alembic/versions/20261020_cl01_fault.py:ro"
                )
                (folder / "compose.yml").write_text(yaml.safe_dump(base, sort_keys=False))
            if mode == "production":
                orphan = env["COMPOSE_PROJECT_NAME"] + "-worker-1"
                run(
                    [
                        "docker",
                        "create",
                        "--name",
                        orphan,
                        "--label",
                        "com.docker.compose.project=" + env["COMPOSE_PROJECT_NAME"],
                        "--label",
                        "com.docker.compose.service=worker",
                        "--label",
                        "com.docker.compose.config-hash=cl01-inert-orphan",
                        "--label",
                        "com.docker.compose.oneoff=False",
                        "--entrypoint",
                        "sleep",
                        "pgvector/pgvector:pg17",
                        "600",
                    ]
                )
                case["inert_legacy_orphan"] = orphan
            with (folder / "deploy.log").open("w") as log:
                proc = subprocess.Popen(
                    ["bash", str(folder / "deploy.sh")],
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
                if mode == "interrupt":
                    for _ in range(180):
                        if proc.poll() is not None:
                            raise AssertionError("deployment exited before interrupted migration")
                        if (
                            sql(
                                "SELECT count(*) FROM pg_stat_activity "
                                "WHERE query='SELECT pg_sleep(120)' AND state='active'"
                            )
                            == "1"
                        ):
                            break
                        time.sleep(0.5)
                    else:
                        raise AssertionError("sleep migration not reached")
                    proc.send_signal(signal.SIGTERM)
                case["exit_code"] = proc.wait(timeout=180)
            expected = (
                0
                if mode == "production"
                else 143
                if mode == "interrupt"
                else 1
                if mode != "preflight-failure"
                else 2
            )
            assert case["exit_code"] == expected, (
                case,
                (folder / "deploy.log").read_text(),
            )
            deploy_log = (folder / "deploy.log").read_text()
            if mode == "migration-failure":
                assert "isolated migration failure" in deploy_log
            if mode == "interrupt":
                assert "deployment interrupted" in deploy_log
                migration = env["COMPOSE_PROJECT_NAME"] + "-migration"
                assert run(["docker", "inspect", migration], check=False).returncode != 0
                case["owned_migration_container_removed"] = True
            if mode == "budget-failure":
                assert "503" in deploy_log and "health check" not in deploy_log
            if mode == "preflight-failure":
                assert "runtime_preflight_failed" in deploy_log
            if mode == "health-failure":
                assert "health check FAILED" in deploy_log
            case["services"] = state()
            assert "worker" not in case["services"]
            case["schema"] = sql("SELECT version_num FROM alembic_version")
            assert case["schema"] == "000017"
            if mode not in ("production", "health-failure"):
                assert not {"api", "web", "r1-worker"} & set(case["services"])
                assert (
                    sql("SELECT coalesce(to_regclass('public.cl01_fault_marker')::text,'absent')")
                    == "absent"
                )
            if mode == "production":
                assert run(["docker", "inspect", orphan], check=False).returncode != 0
                case["orphan_removed"] = True
                case["health"] = healthy()
                for _ in range(30):
                    if int(
                        sql(
                            "SELECT count(*) FROM pipeline_tasks "
                            "WHERE kind='discover' AND status='completed'"
                        )
                    ):
                        break
                    time.sleep(1)
                case["completed_discovery_tasks"] = int(
                    sql(
                        "SELECT count(*) FROM pipeline_tasks "
                        "WHERE kind='discover' AND status='completed'"
                    )
                )
                assert case["completed_discovery_tasks"] >= 1
                run(compose + ["stop"], env)
                run(compose + ["up", "-d", "--remove-orphans"], env)
                run(compose + ["restart", "api", "r1-worker", "web"], env)
                case["health_after_restart"] = healthy()
                for image, supported in ((ROLLBACK, True), (OLDER, False)):
                    heads = run(
                        [
                            "docker",
                            "run",
                            "--rm",
                            "--network",
                            "none",
                            "--entrypoint",
                            "alembic",
                            image,
                            "heads",
                        ]
                    ).stdout.strip()
                    rollback = {
                        "image": image,
                        "image_heads": heads,
                        "supported": supported,
                    }
                    case.setdefault("rollback", []).append(rollback)
                    assert ("000017" in heads) == supported
                    previous_api = run(compose + ["ps", "-q", "api"], env).stdout.strip()
                    previous_worker = run(compose + ["ps", "-q", "r1-worker"], env).stdout.strip()
                    rollback_env = {
                        **env,
                        "SERVER_IMAGE": image,
                        "APP_VERSION": image.rsplit(":", 1)[1],
                    }
                    p = run(["bash", str(folder / "deploy.sh")], rollback_env, check=False)
                    (folder / ("rollback-" + image[-40:-33] + ".log")).write_text(
                        p.stdout + p.stderr
                    )
                    rollback["exit_code"] = p.returncode
                    rollback["schema_after"] = sql("SELECT version_num FROM alembic_version")
                    assert rollback["schema_after"] == "000017"
                    if supported:
                        assert p.returncode == 0, p.stderr
                        rollback["health"] = healthy(environ=rollback_env)
                        reused = run(
                            ["bash", str(folder / "deploy.sh")],
                            {
                                **rollback_env,
                                "SERVER_IMAGE": "",
                                "WEB_IMAGE": "",
                            },
                        )
                        (folder / "immutable-reuse.log").write_text(reused.stdout + reused.stderr)
                        assert "SERVER_IMAGE=" + image in reused.stdout
                        assert "WEB_IMAGE=" + WEB in reused.stdout
                        rollback["immutable_running_images_reused"] = True
                    else:
                        assert p.returncode != 0 and "000017" in p.stdout + p.stderr
                        assert (
                            run(compose + ["ps", "-q", "api"], env).stdout.strip() == previous_api
                        )
                        assert (
                            run(compose + ["ps", "-q", "r1-worker"], env).stdout.strip()
                            == previous_worker
                        )
                        rollback["existing_services_unchanged"] = True
                # Return to current code using the same retired-service files.
                p = run(["bash", str(folder / "deploy.sh")], env)
                (folder / "return-current.log").write_text(p.stdout + p.stderr)
                case["health_after_return"] = healthy()
        case["usage_rows"] = int(sql("SELECT count(*) FROM llm_usage"))
        case["billed_requests"] = int(sql("SELECT count(*) FROM billed_requests"))
        assert case["usage_rows"] == case["billed_requests"] == 0
        case["passed"] = True
        print(mode + ": passed", flush=True)
    except Exception as exc:
        case["error"] = str(exc)
        raise
    finally:
        if proc is not None and proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=15)
        stopped = run(compose + ["stop"], env, check=False)
        case["stop_exit_code"] = stopped.returncode
        case["retained_test_volumes"] = run(
            compose + ["config", "--volumes"], env
        ).stdout.splitlines()
        save()
print(json.dumps(OUT, indent=2))
