"""The implementation gate verifies evidence, never manufactures user acceptance."""

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from unspun.evaluation.r1_benchmark import inspect_benchmark

ROOT = Path(__file__).parents[2]
SUITE = Path("docs/evaluations/r1/technical-suite-v1.json")


def test_real_frozen_technical_benchmark_has_separate_user_and_source_gates() -> None:
    result = inspect_benchmark(ROOT, ROOT / SUITE)
    assert result["technical_ready"] is True
    assert result["user_quality_passed"] is None
    assert result["g2_passed"] is False
    assert result["holdout_inputs"] == 6


@pytest.mark.parametrize(
    "mutation",
    ["identity", "subjective", "missing_holdout", "fingerprint", "scope", "baseline", "budget"],
)
def test_corrupt_technical_evidence_cannot_unlock_g1(tmp_path: Path, mutation: str) -> None:
    root = tmp_path / "repo"
    shutil.copytree(ROOT / "docs", root / "docs")
    for entry in json.loads((ROOT / "docs/evaluations/r1/inputs-v1.json").read_text())["files"]:
        path = Path(entry["path"])
        if not str(path).startswith("docs/"):
            (root / path).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / path, root / path)
    suite: dict[str, Any] = json.loads((root / SUITE).read_text())
    if mutation == "identity":
        suite["reviewer_kind"] = "user"
    elif mutation == "subjective":
        suite["inputs"][0]["technical_expectations"]["user_interest_score"] = 5
    elif mutation == "missing_holdout":
        suite["inputs"].pop()
    elif mutation == "fingerprint":
        suite["pinned_evidence"][0]["sha256"] = "0" * 64
    elif mutation == "scope":
        for item in suite["inputs"]:
            item["scope"] = "none"
    elif mutation == "baseline":
        p = root / suite["baseline_report"]
        d = json.loads(p.read_text())
        d["results"].pop()
        p.write_text(json.dumps(d))
    elif mutation == "budget":
        suite["cost_policy"]["total_all_runs_usd"] = 0.61
    (root / SUITE).write_text(json.dumps(suite))
    with pytest.raises(ValueError):
        inspect_benchmark(root, root / SUITE)
