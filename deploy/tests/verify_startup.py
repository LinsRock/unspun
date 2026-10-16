"""Exercise deployment success, failure, interruption, and retry on fresh Docker volumes.

Requires cached server/web images and a new evidence directory accessible to Docker
bind mounts. Never supplies an LLM key or starts the legacy worker. Cleanup removes
only this invocation's randomly named, disposable Compose projects and volumes.
"""

import argparse
import datetime
import json
import os
import pathlib
import shutil
import signal
import subprocess
import time
import uuid


def stop_process_group(process):
    """Stop the full invocation before removing its Docker resources."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass
    # A parent may already have exited while a descendant still holds pipes.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError:
        # TERM was delivered; a reaped parent can leave an inaccessible dead group.
        if process.poll() is None:
            raise
    process.wait(timeout=5)


def run_command(command, *, env, check=True, timeout=150):
    process = subprocess.Popen(
        command,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except BaseException:
        stop_process_group(process)
        process.communicate()
        raise
    result = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    if check:
        result.check_returncode()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-image", required=True)
    parser.add_argument("--web-image", required=True)
    parser.add_argument("--code-revision", required=True)
    parser.add_argument("--evidence-dir", required=True, type=pathlib.Path)
    parser.add_argument("--base-port", type=int, default=18081)
    args = parser.parse_args()
    ROOT = pathlib.Path(__file__).resolve().parents[2]
    OUT = args.evidence_dir.resolve()
    OUT.mkdir(parents=True, exist_ok=False)
    SHA = args.code_revision
    project_prefix = "unspun-r101-" + uuid.uuid4().hex[:8]
    results = {
        "started_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "image_revision": SHA,
        "cases": [],
    }
    for index, mode in enumerate(("normal", "failure", "interrupt")):
        target = OUT / mode
        target.mkdir(exist_ok=True)
        for name in ("deploy.sh", "compose.yml", "compose.prod.yml"):
            shutil.copy(ROOT / "deploy" / name, target / name)
        prod = (
            (target / "compose.prod.yml")
            .read_text()
            .replace("127.0.0.1:8080:80", f"127.0.0.1:{args.base_port + index}:80")
        )
        if mode != "normal":
            fault = target / "20261016_r101_fault.py"
            fault.write_text(
                'from alembic import op\nrevision="r101_fault"\ndown_revision="000010"\nbranch_labels=None\ndepends_on=None\ndef upgrade():\n    op.execute("CREATE TABLE r101_fault_marker (id integer)")\n'
                + (
                    '    raise RuntimeError("isolated migration failure")\n'
                    if mode == "failure"
                    else '    op.execute("SELECT pg_sleep(120)")\n'
                )
                + "def downgrade():\n    pass\n"
            )
            prod = prod.replace(
                "  api:\n    restart:",
                f"  api:\n    volumes:\n      - {fault}:/app/alembic/versions/20261016_r101_fault.py:ro\n    restart:",
            )
        (target / "compose.prod.yml").write_text(prod)
        envfile = target / ".env"
        envfile.write_text("POSTGRES_PASSWORD=unspun\n")
        env = {
            **os.environ,
            "SERVER_IMAGE": args.server_image,
            "WEB_IMAGE": args.web_image,
            "APP_VERSION": "r101-isolated",
            "COMPOSE_PROJECT_NAME": f"{project_prefix}-{mode}",
            "UNSPUN_DEPLOY_ENV_FILE": str(envfile),
            "UNSPUN_DEPLOY_HEALTH_URL": f"http://127.0.0.1:{args.base_port + index}/api/health",
        }
        compose = [
            "docker",
            "compose",
            "--env-file",
            str(envfile),
            "-f",
            str(target / "compose.yml"),
            "-f",
            str(target / "compose.prod.yml"),
        ]

        def run(args, check=True, environ=env):
            return run_command(args, env=environ, check=check)

        def sql(query, command=compose, execute=run):
            return execute(
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
                ]
            ).stdout.strip()

        case = {"mode": mode, "project": env["COMPOSE_PROJECT_NAME"]}
        proc = None
        try:
            if mode != "normal":
                run(compose + ["up", "-d", "--wait", "--wait-timeout", "120", "db"])
                run(
                    compose
                    + [
                        "run",
                        "--rm",
                        "--no-deps",
                        "api",
                        "alembic",
                        "upgrade",
                        "000010",
                    ]
                )
                case["before_head"] = sql("SELECT version_num FROM alembic_version")
            with (target / "deploy.log").open("w") as log:
                proc = subprocess.Popen(
                    ["bash", str(target / "deploy.sh")],
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                if mode == "interrupt":
                    deadline = time.monotonic() + 140
                    while time.monotonic() < deadline:
                        if proc.poll() is not None:
                            raise AssertionError(f"early exit {proc.returncode}")
                        probe = run(
                            compose
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
                                "SELECT count(*) FROM pg_stat_activity WHERE query = 'SELECT pg_sleep(120)' AND state='active'",
                            ],
                            check=False,
                        )
                        if probe.returncode == 0 and probe.stdout.strip() == "1":
                            break
                        time.sleep(0.25)
                    else:
                        raise AssertionError("migration sleep not reached")
                    proc.send_signal(signal.SIGTERM)
                code = proc.wait(timeout=150)
            case["exit_code"] = code
            assert code == {"normal": 0, "failure": 1, "interrupt": 143}[mode], (
                mode,
                code,
            )
            state = [
                json.loads(line)
                for line in run(
                    compose + ["ps", "--all", "--format", "json"]
                ).stdout.splitlines()
                if line
            ]
            case["services"] = {s["Service"]: s["State"] for s in state}
            assert "worker" not in case["services"]
            case["migration_head"] = sql("SELECT version_num FROM alembic_version")
            case["usage_rows"] = int(sql("SELECT count(*) FROM llm_usage"))
            assert case["usage_rows"] == 0
            case["fault_marker"] = sql(
                "SELECT coalesce(to_regclass('public.r101_fault_marker')::text, 'absent')"
            )
            if mode == "normal":
                assert case["migration_head"] == "000010"
                run(compose + ["restart", "api"])
                time.sleep(2)
                case["health_after_restart"] = json.loads(
                    run(["curl", "-fsS", env["UNSPUN_DEPLOY_HEALTH_URL"]]).stdout
                )
                assert case["health_after_restart"]["version"] == "r101-isolated"
            else:
                assert "api" not in case["services"] and "web" not in case["services"]
                assert (
                    case["migration_head"] == "000010"
                    and case["fault_marker"] == "absent"
                )
                # Remove only the injected bind and retry the same target/volume.
                (target / "compose.prod.yml").write_text(
                    (ROOT / "deploy" / "compose.prod.yml")
                    .read_text()
                    .replace(
                        "127.0.0.1:8080:80", f"127.0.0.1:{args.base_port + index}:80"
                    )
                )
                retry = run(["bash", str(target / "deploy.sh")], check=False)
                (target / "retry.log").write_text(retry.stdout + retry.stderr)
                case["retry_exit_code"] = retry.returncode
                assert retry.returncode == 0, retry.stderr
            case["passed"] = True
        except Exception as exc:
            case["error"] = str(exc)
            raise
        finally:
            if proc is not None:
                stop_process_group(proc)
            results["cases"].append(case)
            results["finished_at"] = datetime.datetime.now(datetime.UTC).isoformat()
            (OUT / "results.json").write_text(
                json.dumps(results, ensure_ascii=False, indent=2) + "\n"
            )
            cleanup = run(
                compose + ["down", "--volumes", "--remove-orphans"], check=False
            )
            (target / "cleanup.log").write_text(cleanup.stdout + cleanup.stderr)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
