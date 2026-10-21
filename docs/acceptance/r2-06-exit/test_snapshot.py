"""The final snapshot must never turn engineering evidence into acceptance."""

import json
import runpy
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
DIRECTORY = Path("docs/acceptance/r2-06-exit")
CHECK = DIRECTORY / "check.py"


@pytest.fixture
def snapshot(tmp_path: Path) -> Path:
    manifest = json.loads((ROOT / DIRECTORY / "inputs.json").read_text())
    sources = json.loads((ROOT / manifest["files"]["sources"]["path"]).read_text())["files"]
    paths = {CHECK, DIRECTORY / "inputs.json"}
    paths.update(Path(ref["path"]) for ref in manifest["files"].values())
    paths.update(Path(path) for path in sources)
    for path in paths:
        destination = tmp_path / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, destination)
    return tmp_path


def run_check(root: Path) -> tuple[int, dict[str, Any]]:
    result = subprocess.run(
        [sys.executable, str(root / CHECK)], capture_output=True, text=True, check=False
    )
    assert not result.stderr
    return result.returncode, json.loads(result.stdout)


def test_recorded_unaccepted_verdict_and_per_request_gaps_are_reproducible() -> None:
    module = runpy.run_path(str(ROOT / CHECK))
    result, gaps = module["verify_snapshot"](ROOT)
    assert result == json.loads((ROOT / DIRECTORY / "result.json").read_text())
    assert gaps == json.loads((ROOT / DIRECTORY / "receipt-gaps.json").read_text())
    code, report = run_check(ROOT)
    assert code == 2
    assert report["candidate"]["real_metrics"] is None
    assert report["last_real_run"]["counts_as_current_candidate_evidence"] is False
    assert report["user_acceptance"] is None


def test_a_saved_green_report_cannot_override_original_evidence(snapshot: Path) -> None:
    (snapshot / DIRECTORY / "result.json").write_text('{"verdict":"accepted"}')
    code, report = run_check(snapshot)
    assert code == 2
    assert report["verdict"] == "not_accepted"


@pytest.mark.parametrize(
    "path",
    [
        "docs/acceptance/r2-06-selection/challenges.json",
        "docs/acceptance/r2-06-selection/final-audit.json",
        "docs/acceptance/r2-06-grounding/exposed-first-run.ndjson",
        "docs/acceptance/r2-06-zero-paid/provider-receipts-v2.json",
        "server/src/unspun/core/member_contracts.py",
        "docs/acceptance/r2-06-exit/inputs.json",
    ],
)
def test_changed_evidence_or_candidate_cannot_be_silently_reaccepted(
    snapshot: Path, path: str
) -> None:
    (snapshot / path).write_text("{}\n")
    code, report = run_check(snapshot)
    assert code == 3
    assert report["verdict"] == "evidence_error"


def test_removing_paid_stop_cannot_open_the_entry(snapshot: Path) -> None:
    (snapshot / "docs/acceptance/r2-06-grounding/paid-stop.json").unlink()
    code, report = run_check(snapshot)
    assert code == 3
    assert report["verdict"] == "evidence_error"
