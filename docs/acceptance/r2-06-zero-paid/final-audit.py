"""Verify deployment and retained evidence without model/provider calls or DB writes."""

import gzip
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

OUT = Path(__file__).parent
ROOT = OUT.parents[2]


def read(name):
    path = OUT / (name + ".json")
    return json.loads(
        path.read_bytes()
        if path.exists()
        else gzip.decompress(path.with_suffix(".json.gz").read_bytes())
    )


revision = read("core-merged")["mergeCommit"]["oid"]
assert read("core-pr-ci")["conclusion"] == "success"
main_ci = read("core-main-ci")
assert main_ci["headSha"] == revision and main_ci["conclusion"] == "success"
deploy = next(job for job in main_ci["jobs"] if job["name"] == "deploy")
assert deploy["conclusion"] == "success"
assert (
    next(step for step in deploy["steps"] if step["name"] == "Deploy")["conclusion"]
    == "success"
)
runtime, chain = read("postdeploy-runtime"), read("postdeploy-member-chain")
assert runtime["health"] == {"status": "ok", "version": revision, "database": "ok"}
assert runtime["legacy_workers"] == 0 and runtime["r1_workers"] == 1
containers = {row["name"]: row for row in runtime["running_containers"]}
old_containers = {
    row["name"]: row for row in read("predeploy-runtime")["running_containers"]
}
for service in ("unspun-api-1", "unspun-r1-worker-1"):
    assert containers[service]["app_version"] == revision
    assert containers[service]["status"] == "running"
assert (
    containers["unspun-api-1"]["image_id"]
    == containers["unspun-r1-worker-1"]["image_id"]
)
assert containers["unspun-web-1"] == old_containers["unspun-web-1"]
assert chain["schema"] == "000019"
assert not chain["configured_member_processing_enabled"]
assert not chain["runtime"]["member_processing_enabled"]
assert chain["member_handlers"] == chain["topic_tasks"] == chain["topic_calls"] == []
assert len(chain["tables"]) == 7 and all(
    t["rows"] == 0 for t in chain["tables"].values()
)
assert chain["policy"] == read("predeploy-member-chain")["policy"]
assert not any(k.startswith("topic_") for k in chain["policy"]["stage_caps"])
local_sources = {
    str(p.relative_to(ROOT / "server/src/unspun")): hashlib.sha256(
        p.read_bytes()
    ).hexdigest()
    for p in (ROOT / "server/src/unspun").rglob("*.py")
}
assert runtime["api_metadata"]["source_sha256"] == local_sources
assert (
    runtime["api_metadata"]["config_sha256"]
    == read("predeploy-runtime")["api_metadata"]["config_sha256"]
)
before, after = (
    read("predeploy-protected-production")["queries"],
    read("postdeploy-protected-production")["queries"],
)
for key in before:
    assert before[key]["rows"] == after[key]["rows"], key
retained = read("predeploy-retained")["tables"]
assert read("postdeploy-retained")["tables"] == retained
before_read, after_read = read("predeploy-reading"), read("postdeploy-reading")
assert (
    after_read["read_only"] == "on"
    and after_read["paid_requests"] == after_read["database_writes"] == 0
)
for key in (
    "published_ids",
    "new_path_published",
    "qualified_details_verified",
    "suspended_nyt_status",
    "recommended",
    "latest",
):
    assert before_read[key] == after_read[key], key
boundaries_before, boundaries_after = (
    read("predeploy-boundaries"),
    read("postdeploy-boundaries"),
)
assert boundaries_after["app_version"] == revision
for key in (
    "settings",
    "runtime",
    "retired_module_present",
    "fixture_directory_present",
):
    assert boundaries_before[key] == boundaries_after[key], key
observation_before, observation_after = (
    read("predeploy-observation"),
    read("postdeploy-observation"),
)
assert observation_before["containers"] == observation_after["containers"]
assert all(
    observation_after["retained_files"].get(k) == v
    for k, v in observation_before["retained_files"].items()
)
assert read("before-recovery")["snapshot"] == read("after-recovery")["snapshot"]
assert read("after-recovery")["all_table_counts_hashes_sequences_match"]
ledgers = {}
for name in ("production", "evaluation"):
    pre, post = read("predeploy-" + name), read("postdeploy-" + name)
    assert post["transaction"]["read_only"] == "on"
    assert post["paid_requests"] == post["database_writes"] == 0
    for field in ("unknown_requests", "known_ledger", "policy", "carry"):
        assert pre[field] == post[field], (name, field)
    ledgers[name] = {
        "unknown_count": len(post["unknown_requests"]),
        "held_usd": sum(
            (Decimal(row["reserved_usd"]) for row in post["unknown_requests"]),
            Decimal(0),
        ),
    }
assert "provider" not in read("postdeploy-production")
assert ledgers["production"] == {"unknown_count": 10, "held_usd": Decimal("0.431089")}
assert ledgers["evaluation"] == {"unknown_count": 8, "held_usd": Decimal("0.514613")}
original_seven = [
    row
    for row in read("ledger-audit")["evaluation"]["rows"]
    if row["protected_original_seven"]
]
assert len(original_seven) == 7
original_holds = sum(
    (Decimal(row["reserved_usd"]) for row in original_seven), Decimal(0)
)
assert original_holds == Decimal("0.484867")
manifest = read("protected-manifest")
for name, digest in manifest["files"].items():
    assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, name
protected = manifest["protected_worktree"]
assert (
    subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=protected["path"], text=True
    ).strip()
    == protected["head"]
)
assert (
    subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=protected["path"], text=True
    )
    == protected["status"]
)
validation = read("validation")
assert validation["regression_passed"] == 1112 and validation["skipped"] == 0
lookups = read("provider-receipts-v2")["generation"]
assert len(lookups) == 12 and all(row.get("http_status") == 404 for row in lookups)
out = {
    "at": datetime.now(UTC).isoformat(),
    "production_revision": revision,
    "source_hashes_match": len(local_sources),
    "production_member_enabled": False,
    "member_tasks": 0,
    "member_calls": 0,
    "empty_member_tables": 7,
    "new_stage_allocations": 0,
    "schema": "000019",
    "legacy_workers": 0,
    "r1_workers": 1,
    "production_protected_queries_unchanged": list(before),
    "retained_tables_unchanged": list(retained),
    "qualified_reading_unchanged": True,
    "qualified_detail_count": len(after_read["qualified_details_verified"]),
    "recommended_latest_first_two_pages_unchanged": True,
    "model_and_runtime_boundaries_unchanged": True,
    "r204_containers_unchanged": len(observation_before["containers"]),
    "r204_original_files_unchanged": len(observation_before["retained_files"]),
    "original_evaluation_all_tables_and_sequences_unchanged": True,
    "protected_artifacts_unchanged": len(manifest["files"]),
    "r204_worktree_unchanged": True,
    "production_unknown_count": ledgers["production"]["unknown_count"],
    "production_holds_usd": format(ledgers["production"]["held_usd"], ".6f"),
    "evaluation_unknown_count": ledgers["evaluation"]["unknown_count"],
    "evaluation_holds_usd": format(ledgers["evaluation"]["held_usd"], ".6f"),
    "original_seven_holds_usd": format(original_holds, ".6f"),
    "paid_generation": 0,
    "paid_embedding": 0,
    "paid_retries": 0,
    "new_blind_prepared_or_read": False,
    "paid_stop_unchanged": True,
    "semantic_pass": False,
    "r206_status": "2/4",
    "user_acceptance": None,
}
with (OUT / "final-audit.json").open("x") as f:
    json.dump(out, f, indent=2)
print(json.dumps(out, indent=2))
