"""Validate the frozen R1 technical benchmark separately from user judgments."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from unspun.evaluation.r1_inputs import inspect_registry, read_object


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect_benchmark(root: Path, suite_path: Path) -> dict[str, Any]:
    registration = inspect_registry(root, root / "docs/evaluations/r1/inputs-v1.json")
    if not registration["registration_valid"]:
        raise ValueError("original evidence registration is invalid")
    suite = read_object(suite_path)
    if suite.get("schema_version") != "r1-technical-suite-v1":
        raise ValueError("unknown technical suite version")
    if (
        suite.get("reviewer_kind") != "ai-technical"
        or suite.get("user_confirmed_thresholds") is not False
    ):
        raise ValueError("technical review must not impersonate user judgment")
    if suite.get("user_quality_status") != "user_quality_pending_final_acceptance":
        raise ValueError("user subjective acceptance remains pending")
    inputs = suite["inputs"]
    ids = [item["id"] for item in inputs]
    if len(set(ids)) != len(ids) or set(ids) != {f"C{i:02}" for i in range(1, 44)} | {
        f"H{i:02}" for i in range(1, 7)
    }:
        raise ValueError("frozen regression/holdout membership changed")
    coverage = Counter(item["scope"] for item in inputs)
    if (
        not {
            "open_text_unit",
            "editorial_edition",
            "complete_brief",
            "preview",
            "question_background",
            "media_description",
            "none",
        }
        <= coverage.keys()
    ):
        raise ValueError("required material boundary is missing")
    original = {
        item["id"]: item
        for item in read_object(root / "docs/research/r0-2026-10-15/candidates.json")["candidates"]
    }
    for item in inputs:
        expected = item["technical_expectations"]
        if (
            expected["user_worth_reading_now"] is not None
            or expected["user_interest_score"] is not None
        ):
            raise ValueError("technical expectations cannot fill subjective user fields")
        if item["split"] == "regression":
            old = original[item["id"]]
            if item["url"] != old["url"] or item["material_sha256"] != old["material_sha256"]:
                raise ValueError("regression input provenance changed")
        elif item["split"] == "holdout":
            if (
                not item["material_sha256"]
                or not item.get("response_sha256")
                or not item["observed_at"]
            ):
                raise ValueError("holdout requires real pinned source material")
        else:
            raise ValueError("unknown evaluation split")
    for entry in suite["pinned_evidence"]:
        relative = Path(entry["path"])
        path = (root / relative).resolve()
        if (
            relative.is_absolute()
            or not path.is_relative_to(root.resolve())
            or digest(path) != entry["sha256"]
        ):
            raise ValueError("frozen technical evidence changed")
    baseline = read_object(root / suite["baseline_report"])
    chosen = {item["id"] for item in inputs if item["live_generation_sample"]}
    results = baseline["results"]
    if {item["id"] for item in results} != chosen or len(results) != len(chosen):
        raise ValueError("before-change output or failure record is missing")
    if any(
        item["variant"] != "legacy-current-summary" or not item["physical_call_ids"]
        for item in results
    ):
        raise ValueError("baseline must be actual old-contract model output or recorded attempt")
    legacy = read_object(root / suite["legacy_regression_report"])
    if legacy.get("passed") is not True or legacy.get("ready") is not True:
        raise ValueError("legacy event regression did not pass")
    policy = read_object(root / suite["source_observation_policy"]["path"])
    if (
        digest(root / suite["source_observation_policy"]["path"])
        != suite["source_observation_policy"]["sha256"]
    ):
        raise ValueError("source observation window changed")
    continuous = policy["continuous_routes"]
    if (
        continuous["minimum_elapsed_seconds"] < 21600
        or continuous["minimum_distinct_calendar_days"] < 2
    ):
        raise ValueError("target observation gate is incomplete")
    if any(value != 0 for value in suite["critical_thresholds"].values()):
        raise ValueError("critical correctness thresholds must not permit errors")
    if (
        suite["cost_policy"]["total_all_runs_usd"] > 0.60
        or suite["cost_policy"]["raise_budget_or_change_model"] is not False
    ):
        raise ValueError("evaluation allocation exceeds the registered cap")
    return {
        "schema_version": "r1-technical-readiness-v1",
        "technical_ready": True,
        "user_quality_passed": None,
        "user_quality_status": "user_quality_pending_final_acceptance",
        "reviewer_kind": "ai-technical",
        "suite_sha256": digest(suite_path),
        "regression_inputs": 43,
        "holdout_inputs": 6,
        "baseline_samples": len(results),
        "baseline_failed_attempts": sum(item["status"] == "failed" for item in results),
        "material_scope_counts": dict(coverage),
        "g2_passed": False,
        "note": (
            "Benchmark readiness permits implementation; candidate technical quality, "
            "source gates and final user acceptance are separate."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("readiness output exists; preserve original evidence")
    report = inspect_benchmark(args.root, args.suite)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"technical_ready={report['technical_ready']} user_quality=pending_final_acceptance")


if __name__ == "__main__":
    main()
