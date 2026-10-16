"""Select checks and release artifacts from changed paths; fail closed on diff errors."""

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

CHECKS = ("server", "web", "prototype", "deploy")
KEYS = (*CHECKS, "server_image", "web_image", "release")
JOBS = {
    "server": "server",
    "web": "web",
    "prototype": "admin-prototype",
    "deploy": "deploy-safety",
}


def classify(paths, *, full=False):
    selected = set(CHECKS) if full else set()
    for path in paths:
        if path.startswith((".github/",)):
            selected.update(CHECKS)
        elif path.startswith("docs/design/m3a-admin-react/") and not path.endswith(
            ".md"
        ):
            selected.add("prototype")
        elif path.startswith(
            (
                "docs/evaluations/",
                "docs/research/",
                "docs/feedback/",
                "docs/design/r0-reading/",
                "docs/acceptance/r0-reading-",
            )
        ):
            selected.add("server")
        elif (
            ("/" not in path and path.endswith(".md"))
            or path.startswith("docs/")
            or path
            in (
                "LICENSE",
                ".gitignore",
                "server/README.md",
                "server/eval/README.md",
                "web/README.md",
                "web/src/DESIGN.md",
            )
        ):
            continue
        elif path.startswith("server/"):
            selected.add("server")
            if not path.startswith(
                ("server/tests/", "server/eval/", "server/src/unspun/evaluation/")
            ):
                selected.update(("server_image", "release"))
            if path.startswith("server/src/unspun/api/") or path in (
                "server/pyproject.toml",
                "server/uv.lock",
                "server/src/unspun/core/config.py",
            ):
                selected.add("web")
        elif path.startswith("web/"):
            selected.add("web")
            test_file = Path(path).suffix in (
                ".ts",
                ".tsx",
                ".js",
                ".jsx",
                ".mjs",
                ".mts",
            ) and (".test." in path or ".spec." in path)
            if not (path.startswith(("web/tests/", "web/e2e/")) or test_file):
                selected.update(("web_image", "release"))
        elif path.startswith("config/") or path == "deploy/server.Dockerfile":
            selected.update(("server", "deploy", "server_image", "release"))
        elif path in ("deploy/web.Dockerfile", "deploy/Caddyfile"):
            selected.update(("web", "deploy", "web_image", "release"))
        elif path.startswith("deploy/tests/"):
            selected.add("deploy")
        elif path in (
            "deploy/deploy.sh",
            "deploy/compose.yml",
            "deploy/compose.prod.yml",
        ):
            selected.update(("server", "web", "deploy", "release"))
        elif path == "deploy/compose.local.yml":
            selected.update(("server", "web", "deploy"))
        else:
            # Unknown build inputs must not silently avoid tests or publication.
            selected.update(KEYS)
    return {key: "true" if key in selected else "false" for key in KEYS}


def changed_paths(base, head, *, pull_request=False, include_history=False, cwd=None):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=cwd)

    if base == "0" * 40:
        output = git("ls-tree", "-rz", "--name-only", head)
    else:
        if pull_request:
            base = git("merge-base", base, head).decode().strip()
        # A rename also removes its old path, which may have a different scope.
        output = git("diff", "--no-renames", "--name-only", "-z", base, head)
        if include_history:
            # Failed health checks may leave changed services running. Include
            # reverted changes even when a later docs commit is now main.
            output += git(
                "log",
                "--first-parent",
                "--diff-merges=first-parent",
                "--format=",
                "--name-only",
                "--no-renames",
                "-z",
                f"{base}..{head}",
            )
    return list(dict.fromkeys(name.decode() for name in output.split(b"\0") if name))


def gh_api(endpoint):
    return json.loads(subprocess.check_output(["gh", "api", endpoint], timeout=20))


def last_released_sha(repository):
    # Query production deployments, not every successful CI run. Docs-only
    # runs do not create deployment records; obsolete skipped steps are ignored.
    try:
        page = 1
        while True:
            deployments = gh_api(
                f"repos/{repository}/deployments?environment=production&per_page=100&page={page}"
            )
            for deployment in deployments:
                statuses = gh_api(
                    f"repos/{repository}/deployments/{deployment['id']}/statuses?per_page=100"
                )
                for status in statuses:
                    if status.get("state") != "success":
                        continue
                    job_id = re.search(r"/job/(\d+)$", status.get("log_url") or "")
                    if not job_id:
                        continue
                    job = gh_api(f"repos/{repository}/actions/jobs/{job_id[1]}")
                    if job["conclusion"] == "success" and any(
                        step["name"] == "Deploy" and step["conclusion"] == "success"
                        for step in job["steps"]
                    ):
                        return deployment["sha"]
            if len(deployments) < 100:
                break
            page += 1
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        print("Release history unavailable; checking all repository inputs.")
    return "0" * 40


def verify_needs(needs):
    for job, value in needs.items():
        if value["result"] not in ("success", "skipped"):
            raise ValueError(f"required job did not pass: {job}")
    for job in ("changes", "conventions"):
        if needs[job]["result"] != "success":
            raise ValueError(f"mandatory job did not pass: {job}")
    scope = needs["changes"]["outputs"]
    for key, job in JOBS.items():
        if scope[key] not in ("true", "false"):
            raise ValueError(f"invalid scope: {key}")
        if scope[key] == "true" and needs[job]["result"] != "success":
            raise ValueError(f"selected check was skipped: {job}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-needs", action="store_true")
    args = parser.parse_args()
    if args.verify_needs:
        verify_needs(json.loads(os.environ["CI_NEEDS"]))
        print("All selected checks passed.")
        return
    event_name = os.environ["GITHUB_EVENT_NAME"]
    if event_name == "workflow_dispatch":
        scope = classify([], full=True)
    else:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        is_pr = event_name == "pull_request"
        base = (
            event["pull_request"]["base"]["sha"]
            if is_pr
            else last_released_sha(os.environ["GITHUB_REPOSITORY"])
        )
        head = event["pull_request"]["head"]["sha"] if is_pr else event["after"]
        scope = classify(
            changed_paths(base, head, pull_request=is_pr, include_history=not is_pr)
        )
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as stream:
        stream.writelines(f"{key}={value}\n" for key, value in scope.items())
    print(json.dumps(scope, sort_keys=True))


if __name__ == "__main__":
    main()
