"""Fault-injection checks for the production deployment boundary (no network)."""

import json
import os
import pty
import shutil
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


class DeploymentSafety(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copy(Path(__file__).parents[1] / "deploy.sh", self.root)
        self.log = self.root / "calls.jsonl"
        self.env = {
            **os.environ,
            "PATH": f"{self.root}:{os.environ['PATH']}",
            "CALL_LOG": str(self.log),
            "SERVER_IMAGE": "server:target",
            "WEB_IMAGE": "web:target",
            "APP_VERSION": "target",
            "COMPOSE_PROJECT_NAME": "isolated",
        }
        self.executable(
            "docker",
            """import json, os, signal, sys, time
args = sys.argv[1:]
with open(os.environ["CALL_LOG"], "a") as log:
    log.write(json.dumps(args) + "\\n")
phase = os.environ.get("FAIL_PHASE")
if args[0] == "compose":
    if "pull" in args and phase == "pull": sys.exit(41)
    if "--wait" in args and phase == "db": sys.exit(42)
    if "run" in args:
        if sys.stdout.isatty() and not sys.stdin.isatty() and "-T" not in args:
            print("the input device is not a TTY", file=sys.stderr)
            sys.exit(1)
        if phase == "migration": sys.exit(43)
        if phase == "interrupt":
            signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
            while True: time.sleep(0.05)
    if "ps" in args:
        service = args[-1]
        if service == "rsshub": print("isolated-rsshub-1")
        elif os.environ.get("ACTIVE_" + service.upper()): print("active-" + service)
if args[0] == "inspect":
    if ".Config.Image" in args[2]:
        service = args[-1].removeprefix("active-")
        print(os.environ["ACTIVE_" + service.upper()])
    elif "io.unspun.deployment" in args[2]:
        if os.environ.get("OTHER_OWNER"): print("another-deployment")
        else:
            with open(os.environ["CALL_LOG"]) as log:
                for line in log:
                    call = json.loads(line)
                    if "--label" in call:
                        print(call[call.index("--label")+1].split("=",1)[1])
    else: print("healthy")
""",
        )
        self.executable(
            "curl",
            'import os; print(\'{"status":"ok","version":"\' + '
            'os.environ.get("HEALTH_VERSION", "target") + \'","database":"ok"}\')',
        )
        self.executable("sleep", "")

    def executable(self, name, source):
        path = self.root / name
        path.write_text(f"#!/usr/bin/env python3\n{source}\n")
        path.chmod(0o755)

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def run_deploy(self, **env):
        return subprocess.run(
            ["bash", str(self.root / "deploy.sh")],
            env={**self.env, **env},
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )

    def test_success_orders_database_migration_then_services(self):
        result = self.run_deploy()
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        db = next(i for i, args in enumerate(calls) if "--wait" in args)
        migration = next(i for i, args in enumerate(calls) if "run" in args)
        start = next(i for i, args in enumerate(calls) if "--remove-orphans" in args)
        self.assertLess(db, migration)
        self.assertLess(migration, start)
        self.assertEqual(calls[db][-1], "db")
        self.assertIn("--no-deps", calls[migration])
        self.assertEqual(calls[migration][-4:], ["api", "alembic", "upgrade", "head"])
        self.assertIn("worker=0", calls[start])

    def test_failures_do_not_start_target_services(self):
        for phase, code in (("pull", 41), ("db", 42), ("migration", 43)):
            with self.subTest(phase=phase):
                self.log.unlink(missing_ok=True)
                result = self.run_deploy(FAIL_PHASE=phase)
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertFalse(
                    any("--remove-orphans" in args for args in self.calls())
                )

    def test_unresolved_image_stops_before_pull_or_migration(self):
        result = self.run_deploy(SERVER_IMAGE="")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any("pull" in args or "run" in args for args in self.calls()))

    def test_web_only_release_reuses_immutable_running_server(self):
        image = "ghcr.io/linsrock/unspun-server:" + "a" * 40
        result = self.run_deploy(SERVER_IMAGE="", ACTIVE_API=image)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SERVER_IMAGE=" + image, result.stdout)
        self.assertIn("WEB_IMAGE=web:target", result.stdout)

    def test_server_only_release_reuses_running_web_digest(self):
        image = "ghcr.io/linsrock/unspun-web@sha256:" + "b" * 64
        result = self.run_deploy(WEB_IMAGE="", ACTIVE_WEB=image)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("WEB_IMAGE=" + image, result.stdout)

    def test_deploy_only_reuses_both_and_refuses_mutable_images(self):
        result = self.run_deploy(
            SERVER_IMAGE="", WEB_IMAGE="",
            ACTIVE_API="server:" + "a" * 40, ACTIVE_WEB="web:" + "b" * 40,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.log.unlink()
        result = self.run_deploy(SERVER_IMAGE="", ACTIVE_API="server:latest")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any("pull" in args or "run" in args for args in self.calls()))

    def test_terminal_output_with_closed_stdin_can_migrate(self):
        master, slave = pty.openpty()
        try:
            result = subprocess.run(
                ["bash", str(self.root / "deploy.sh")],
                env=self.env,
                stdin=subprocess.DEVNULL,
                stdout=slave,
                stderr=slave,
                check=False,
                timeout=15,
            )
            self.assertEqual(result.returncode, 0)
        finally:
            os.close(slave)
            os.close(master)

    def test_old_healthy_api_cannot_pass_target_smoke_check(self):
        result = self.run_deploy(HEALTH_VERSION="previous")
        self.assertEqual(result.returncode, 1)
        self.assertIn("health check FAILED", result.stderr)

    def interrupt_migration(self, other_owner=False):
        process = subprocess.Popen(
            ["bash", str(self.root / "deploy.sh")],
            env={
                **self.env,
                "FAIL_PHASE": "interrupt",
                "OTHER_OWNER": "yes" if other_owner else "",
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if self.log.exists() and any("run" in args for args in self.calls()):
                    break
                time.sleep(0.02)
            else:
                self.fail("migration did not start")
            process.send_signal(signal.SIGTERM)
            _, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 143, stderr)
            self.assertFalse(any("--remove-orphans" in args for args in self.calls()))
            cleanup = ["rm", "-f", "isolated-migration"]
            if other_owner:
                self.assertNotIn(cleanup, self.calls())
            else:
                self.assertIn(cleanup, self.calls())
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    def test_sigterm_during_migration_cleans_container_and_does_not_start(self):
        self.interrupt_migration()

    def test_interrupt_cannot_remove_another_deployments_migration(self):
        self.interrupt_migration(other_owner=True)


if __name__ == "__main__":
    unittest.main()
