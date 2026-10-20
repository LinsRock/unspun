"""Assert the recorded R2-04 deployment boundaries; no external calls or writes to services."""

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

folder = Path(__file__).parent
repo = folder.parents[2]


def read(name):
    return json.loads((folder / name).read_text())


pr = read("pr.json")
revision = pr["mergeCommit"]["oid"]
runtime = read("postdeploy-runtime.json")
audit = read("postdeploy-audit.json")
before = read("preflight-production.json")
after = read("postdeploy-production.json")
pre_boundary = read("predeploy-boundaries.json")
post_boundary = read("postdeploy-boundaries.json")
pre_reading = read("predeploy-reading.json")
post_reading = read("postdeploy-reading.json")
pre_eval = read("preflight-evaluation.json")
post_eval = read("postdeploy-evaluation.json")
pre_protected = read("predeploy-protected-production.json")
post_protected = read("postdeploy-protected-production.json")
ci = read("main-ci.json")

assert pr["state"] == "MERGED"
assert any(
    job["name"] == "deploy"
    and job["conclusion"] == "success"
    and any(
        step["name"] == "Deploy" and step["conclusion"] == "success"
        for step in job["steps"]
    )
    for job in ci["jobs"]
)
assert runtime["health"] == {"status": "ok", "version": revision, "database": "ok"}
assert runtime["api_metadata"]["schema"] == "000017"
for path, expected in runtime["api_metadata"]["source_sha256"].items():
    assert (
        hashlib.sha256((repo / "server/src/unspun" / path).read_bytes()).hexdigest()
        == expected
    )
for path, expected in runtime["api_metadata"]["config_sha256"].items():
    assert hashlib.sha256((repo / "config" / path).read_bytes()).hexdigest() == expected
assert audit["legacy_all_states"] == 0 and audit["controlled_running"] == 1
containers = {c["service"]: c for c in audit["containers"]}
assert containers["api"]["image"] == containers["r1-worker"]["image"]
assert containers["api"]["image"].endswith(":" + revision)
assert containers["api"]["image_id"] == containers["r1-worker"]["image_id"]
pre_containers = {c["service"]: c for c in read("predeploy-runtime.json")["containers"]}
assert containers["web"]["image"] == pre_containers["web"]["image"]
assert containers["web"]["ports"] == {
    "80/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8080"}]
}
assert not containers["api"]["mounts"] and not containers["r1-worker"]["mounts"]
assert pre_boundary["settings"] == post_boundary["settings"]
assert pre_boundary["runtime"]["stages"] == post_boundary["runtime"]["stages"]
assert pre_boundary["runtime"]["publication"] == post_boundary["runtime"]["publication"]
assert post_boundary["retired_module_present"] == {"main": False, "fetcher": False}
active = pre_boundary["runtime"]["publication"]
old_sources = {s["id"]: s for s in before["sources"]}
new_sources = {s["id"]: s for s in after["sources"]}
assert all(old_sources[name] == new_sources[name] for name in active)
for name in ("thepaper-sidebar", "36kr-newsflashes"):
    source = new_sources[name]
    assert not source["legacy_enabled"] and source["discovery_owner"] == "r1"
    assert source["r1"]["quotas"] == {
        "scan": 30,
        "material": 1,
        "paid": 1,
        "recheck_seconds": 86400,
    }
    assert not any(
        source["r1"][flag] for flag in ("discovery", "material", "paid", "publish")
    )
    assert source["r1"]["paid_scopes"] == [] == source["r1"]["publish_scopes"]
assert before["models"] == after["models"]
assert pre_eval["known_ledger"] == post_eval["known_ledger"]
assert pre_eval["unknown_requests"] == post_eval["unknown_requests"]
assert pre_eval["policy"] == post_eval["policy"]
assert len(post_eval["unknown_requests"]) == 7
for name in (
    "legacy_articles",
    "legacy_summary_pending",
    "legacy_summary_abandoned",
    "legacy_runs",
    "digests",
    "policy",
):
    assert pre_protected["queries"][name] == post_protected["queries"][name]
assert pre_reading["published_ids"] == post_reading["published_ids"]
assert sorted(
    pre_reading["qualified_details_verified"], key=lambda r: r["id"]
) == sorted(post_reading["qualified_details_verified"], key=lambda r: r["id"])
assert post_reading["new_path_published"] == 0
assert post_reading["tasks_before"] == post_reading["tasks_after"]
assert post_reading["suspended_nyt_status"] == 404
for sort in ("recommended", "latest"):
    assert pre_reading[sort] == post_reading[sort]
delta = Decimal(after["known_ledger"][0]["known_usd"]) - Decimal(
    before["known_ledger"][0]["known_usd"]
)
out = {
    "schema_version": "r2-04-delivery-v1",
    "verified_at": datetime.now(UTC).isoformat(),
    "assertions_passed": True,
    "runtime_revision": revision,
    "implementation_pr": pr["url"],
    "actual_deploy_step_ran": True,
    "legacy_workers_all_states": 0,
    "controlled_workers": 1,
    "original_eight_unchanged": active,
    "new_paths_all_stages_off": True,
    "published_qualified_details_before_and_after": len(post_reading["published_ids"]),
    "new_paths_published_readable_increment": 0,
    "new_paid_requests": 0,
    "new_paid_usd": "0",
    "original_evaluation_known_usd": post_eval["known_ledger"][0]["known_usd"],
    "original_unknown_requests_retained": 7,
    "original_unknown_holds_usd": post_eval["budget"]["reserved_usd"],
    "natural_production_known_delta_usd": str(delta),
    "natural_delta_is_not_test_spend": True,
    "r2_04_complete": False,
    "remaining": [
        "cross-cache/cross-date window and real new/repeated identities",
        "critical-field/material audit",
        "fresh registered paid current-contract evaluation",
        "budget-qualified separate enablement PR and actual readable increment",
    ],
}
with (folder / "delivery.json").open("x") as handle:
    json.dump(out, handle, indent=2)
    handle.write("\n")
print(json.dumps(out, ensure_ascii=False))
