"""Release routing and required-check guards, including real git rename/history cases."""

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "ci_scope", Path(__file__).parents[1] / "scripts/ci_scope.py"
)
SCOPE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCOPE)


class ScopeChecks(unittest.TestCase):
    def selected(self, *paths):
        return {key for key, value in SCOPE.classify(paths).items() if value == "true"}

    def test_docs_and_offline_evaluation_do_not_publish(self):
        self.assertEqual(self.selected("docs/tasks/r1.md", "CLAUDE.md"), set())
        self.assertEqual(
            self.selected("server/src/unspun/evaluation/r1_inputs.py"), {"server"}
        )
        self.assertEqual(
            self.selected("docs/evaluations/r1/inputs-v1.json"), {"server"}
        )
        self.assertEqual(self.selected("server/tests/test_content.py"), {"server"})

    def test_runtime_and_migrations_build_only_server(self):
        expected = {"server", "server_image", "release"}
        self.assertEqual(self.selected("server/prompts/card.md"), expected)
        self.assertEqual(
            self.selected("server/src/unspun/pipeline/r1_worker.py"), expected
        )
        self.assertEqual(self.selected("server/alembic/versions/new.py"), expected)

    def test_api_and_dependency_changes_also_check_frontend(self):
        for path in ("server/src/unspun/api/contents.py", "server/uv.lock"):
            self.assertEqual(
                self.selected(path), {"server", "web", "server_image", "release"}
            )

    def test_frontend_and_proxy_build_only_web(self):
        self.assertEqual(
            self.selected("web/src/App.tsx"), {"web", "web_image", "release"}
        )
        self.assertEqual(self.selected("web/src/App.test.tsx"), {"web"})
        self.assertEqual(
            self.selected("deploy/Caddyfile"), {"web", "deploy", "web_image", "release"}
        )

    def test_deployment_can_reuse_images_but_tests_do_not_release(self):
        self.assertEqual(
            self.selected("deploy/deploy.sh"), {"server", "web", "deploy", "release"}
        )
        self.assertEqual(self.selected("deploy/tests/test_deploy.py"), {"deploy"})

    def test_ci_and_unknown_inputs_cannot_bypass_validation(self):
        self.assertEqual(self.selected(".github/workflows/ci.yml"), set(SCOPE.CHECKS))
        self.assertEqual(self.selected(".dockerignore"), set(SCOPE.KEYS))
        self.assertEqual(
            self.selected("docs/design/m3a-admin-react/src/App.tsx"), {"prototype"}
        )
        scope = SCOPE.classify([], full=True)
        self.assertEqual(
            {key for key, value in scope.items() if value == "true"}, set(SCOPE.CHECKS)
        )

    def test_release_baseline_ignores_docs_and_obsolete_release_jobs(self):
        deployments = [{"id": i, "sha": str(i) * 40} for i in (3, 2, 1)]

        def success(i):
            return [
                {"state": "success", "log_url": None},
                {
                    "state": "success",
                    "log_url": f"https://github.com/owner/repo/actions/runs/9/job/{i}",
                },
            ]

        obsolete = {
            "conclusion": "success",
            "steps": [{"name": "Deploy", "conclusion": "skipped"}],
        }
        released = {
            "conclusion": "success",
            "steps": [{"name": "Deploy", "conclusion": "success"}],
        }
        with patch.object(
            SCOPE,
            "gh_api",
            side_effect=[deployments, success(3), obsolete, [], success(1), released],
        ) as api:
            self.assertEqual(SCOPE.last_released_sha("owner/repo"), "1" * 40)
            self.assertIn(
                "deployments?environment=production", api.call_args_list[0].args[0]
            )
        with patch.object(SCOPE, "gh_api", side_effect=ValueError("unavailable")):
            self.assertEqual(SCOPE.last_released_sha("owner/repo"), "0" * 40)

    def test_release_history_follows_pages_instead_of_releasing_for_docs(self):
        def response(endpoint):
            if endpoint.endswith("page=1"):
                return [{"id": i, "sha": "0" * 40} for i in range(100)]
            if endpoint.endswith("page=2"):
                return [{"id": 100, "sha": "a" * 40}]
            if "/deployments/100/statuses" in endpoint:
                return [
                    {
                        "state": "success",
                        "log_url": "https://github.com/owner/repo/actions/runs/9/job/100",
                    }
                ]
            if endpoint.endswith("/actions/jobs/100"):
                return {
                    "conclusion": "success",
                    "steps": [{"name": "Deploy", "conclusion": "success"}],
                }
            return []

        with patch.object(SCOPE, "gh_api", side_effect=response) as api:
            self.assertEqual(SCOPE.last_released_sha("owner/repo"), "a" * 40)
            self.assertTrue(
                any(call.args[0].endswith("page=2") for call in api.call_args_list)
            )

    def test_required_gate_rejects_failed_cancelled_or_skipped_selected_checks(self):
        needs = {
            "changes": {
                "result": "success",
                "outputs": SCOPE.classify(["web/src/App.tsx"]),
            },
            "conventions": {"result": "success"},
            **{job: {"result": "skipped"} for job in SCOPE.JOBS.values()},
        }
        with self.assertRaises(ValueError):
            SCOPE.verify_needs(needs)
        needs["web"]["result"] = "success"
        SCOPE.verify_needs(needs)
        for result in ("failure", "cancelled"):
            needs["web"]["result"] = result
            with self.assertRaises(ValueError):
                SCOPE.verify_needs(needs)

    def test_real_git_diff_includes_both_sides_of_rename_and_pr_merge_base(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def git(*args):
                return (
                    subprocess.check_output(
                        ["git", *args], cwd=root, stderr=subprocess.DEVNULL
                    )
                    .decode()
                    .strip()
                )

            def commit():
                git("add", ".")
                git(
                    "-c",
                    "user.name=CI",
                    "-c",
                    "user.email=ci@example.com",
                    "commit",
                    "-qm",
                    "fixture",
                )
                return git("rev-parse", "HEAD")

            git("init", "-q")
            (root / "server").mkdir()
            (root / "server/entry.py").write_text("runtime")
            base = commit()
            git("checkout", "-qb", "feature")
            (root / "docs").mkdir()
            git("mv", "server/entry.py", "docs/entry.md")
            head = commit()
            self.assertEqual(
                set(SCOPE.changed_paths(base, head, cwd=root)),
                {"server/entry.py", "docs/entry.md"},
            )
            self.assertEqual(
                set(SCOPE.changed_paths("0" * 40, head, cwd=root)), {"docs/entry.md"}
            )
            git("checkout", "-q", "--detach", base)
            (root / "unrelated.md").write_text("base branch progress")
            advanced_base = commit()
            self.assertEqual(
                set(
                    SCOPE.changed_paths(
                        advanced_base, head, pull_request=True, cwd=root
                    )
                ),
                {"server/entry.py", "docs/entry.md"},
            )

    def test_reverted_runtime_and_later_docs_still_publish_after_a_failed_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def git(*args):
                return (
                    subprocess.check_output(
                        ["git", *args], cwd=root, stderr=subprocess.DEVNULL
                    )
                    .decode()
                    .strip()
                )

            def commit():
                git("add", ".")
                git(
                    "-c",
                    "user.name=CI",
                    "-c",
                    "user.email=ci@example.com",
                    "commit",
                    "-qm",
                    "fixture",
                )
                return git("rev-parse", "HEAD")

            git("init", "-q")
            (root / "server").mkdir()
            source = root / "server/app.py"
            source.write_text("good")
            baseline = commit()
            source.write_text("bad release")
            commit()
            source.write_text("good")
            reverted = commit()
            self.assertEqual(SCOPE.changed_paths(baseline, reverted, cwd=root), [])
            (root / "note.md").write_text("later main commit")
            head = commit()
            paths = SCOPE.changed_paths(baseline, head, include_history=True, cwd=root)
            self.assertIn("server/app.py", paths)
            self.assertEqual(SCOPE.classify(paths)["server_image"], "true")
            self.assertEqual(SCOPE.classify(paths)["release"], "true")


if __name__ == "__main__":
    unittest.main()
