"""Verify actual R2-06 production evidence; never changes runtime or billing."""

import argparse
import json
from decimal import Decimal
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--revision", required=True)
args = parser.parse_args()
root = Path(__file__).parent


def read(name):
    return json.loads((root / name).read_text())


pre, post = {}, {}
for name in (
    "runtime",
    "reading",
    "production",
    "evaluation",
    "protected-production",
    "boundaries",
    "observation",
    "retained",
    "member-chain",
):
    pre[name], post[name] = (
        read("predeploy-" + name + ".json"),
        read("postdeploy-" + name + ".json"),
    )
audit, schema = read("postdeploy-audit.json"), read("postdeploy-schema.json")
checks = {}
checks["target_api_health"] = post["runtime"]["health"]["version"] == args.revision
checks["schema_and_image_migration_head"] = post["runtime"]["api_metadata"][
    "schema"
] == schema["schema"] == "000019" and schema["migration_heads"] == ["000019"]
checks["seven_topic_pipeline_tables_empty"] = len(schema["tables"]) == 7 and all(
    t["rows"] == 0 for t in schema["tables"].values()
)
local = read("import-check.json")
checks["current_api_source"] = (
    post["runtime"]["api_metadata"]["source_sha256"] == local["source_sha256"]
)
checks["config_unchanged"] = (
    pre["runtime"]["api_metadata"]["config_sha256"]
    == post["runtime"]["api_metadata"]["config_sha256"]
)
checks["unchanged_web_image_reused"] = next(
    c["image"]
    for c in pre["runtime"]["running_containers"]
    if c["name"] == "unspun-web-1"
) == next(
    c["image"]
    for c in post["runtime"]["running_containers"]
    if c["name"] == "unspun-web-1"
)
api = next(c for c in audit["containers"] if c["service"] == "api")
worker = next(c for c in audit["containers"] if c["service"] == "r1-worker")
checks["fixed_api_worker_image_and_version"] = (
    api["image"] == worker["image"] == "ghcr.io/linsrock/unspun-server:" + args.revision
    and api["image_id"] == worker["image_id"]
    and api["app_version"] == worker["app_version"] == args.revision
)
checks["no_api_worker_observation_mounts"] = api["mounts"] == worker["mounts"] == []
checks["legacy_retired_controlled_one"] = (
    audit["legacy_all_states"] == 0
    and audit["controlled_running"] == 1
    and "worker" not in audit["services"]
)
checks["only_original_published_port"] = [
    (c["service"], c["ports"]) for c in audit["containers"] if c["ports"]
] == [("web", {"80/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8080"}]})]
checks["original_sources_models_runtime_contracts"] = (
    pre["production"]["sources"] == post["production"]["sources"]
    and pre["production"]["models"] == post["production"]["models"]
    and pre["production"]["contracts"] == post["production"]["contracts"]
)
checks["reading_and_existing_details_unchanged"] = all(
    pre["reading"][key] == post["reading"][key]
    for key in (
        "published_ids",
        "qualified_details_verified",
        "recommended",
        "latest",
        "suspended_nyt_status",
    )
)
checks["reading_remains_read_only"] = all(
    value["tasks_before"] == value["tasks_after"]
    and value["paid_requests"] == value["database_writes"] == 0
    for value in (pre["reading"], post["reading"])
)
checks["new_source_publications_zero"] = (
    pre["reading"]["new_path_published"] == post["reading"]["new_path_published"] == 0
)
new_sources = [
    s
    for s in post["production"]["sources"]
    if s["id"] in ("thepaper-sidebar", "36kr-newsflashes")
]
checks["new_sources_all_stages_and_scopes_closed"] = len(new_sources) == 2 and all(
    not any(s["r1"][stage] for stage in ("discovery", "material", "paid", "publish"))
    and s["r1"]["paid_scopes"] == s["r1"]["publish_scopes"] == []
    for s in new_sources
)
checks["original_eval_known_unknown_policy_carry_unchanged"] = all(
    pre["evaluation"][k] == post["evaluation"][k]
    for k in ("known_ledger", "unknown_requests", "policy", "carry")
)
checks["original_events_identity_reader_unchanged"] = (
    pre["retained"]["tables"] == post["retained"]["tables"]
)
checks["legacy_backlog_runs_digests_policy_unchanged"] = all(
    pre["protected-production"]["queries"][key]
    == post["protected-production"]["queries"][key]
    for key in (
        "legacy_articles",
        "legacy_summary_pending",
        "legacy_summary_abandoned",
        "legacy_runs",
        "digests",
        "source_ownership",
        "policy",
        "unknown",
    )
)
old_observers = {c["name"]: c for c in pre["observation"]["containers"]}
new_observers = {c["name"]: c for c in post["observation"]["containers"]}
checks["r204_observers_preserved"] = all(
    new_observers.get(name) == value for name, value in old_observers.items()
)
checks["r204_preexisting_raw_files_preserved"] = all(
    post["observation"]["retained_files"].get(name) == value
    for name, value in pre["observation"]["retained_files"].items()
)
checks["member_chain_config_and_handlers_off"] = (
    post["member-chain"]["configured_member_processing_enabled"] is False
    and post["member-chain"]["runtime"]["member_processing_enabled"] is False
    and post["member-chain"]["member_handlers"] == []
)
checks["no_automatic_topic_tasks_or_paid_calls"] = (
    pre["member-chain"]["topic_tasks"] == post["member-chain"]["topic_tasks"] == []
    and pre["member-chain"]["topic_calls"] == post["member-chain"]["topic_calls"] == []
)
checks["existing_budget_policy_unchanged_new_stages_unallocated"] = (
    pre["member-chain"]["policy"] == post["member-chain"]["policy"]
    and all(Decimal(str(post["member-chain"]["policy"]["stage_caps"].get(k, 0))) == 0
            for k in ("topic_embedding", "topic_judgment", "topic_review"))
)
delta = Decimal(post["production"]["known_ledger"][0]["known_usd"]) - Decimal(
    pre["production"]["known_ledger"][0]["known_usd"]
)
checks["production_no_unknown_holds_released"] = (
    pre["production"]["unknown_requests"] == post["production"]["unknown_requests"]
)
out = {
    "revision": args.revision,
    "checks": checks,
    "all_passed": all(checks.values()),
    "qualified_details": len(post["reading"]["qualified_details_verified"]),
    "original_eval_unresolved_count": len(post["evaluation"]["unknown_requests"]),
    "production_known_fee_delta_during_observation": str(delta),
    "new_test_paid_requests": 0,
    "new_test_paid_usd": "0",
    "production_topic_backfill": 0,
    "r204_remains_incomplete": True,
    "r206_remains_incomplete": True,
    "production_member_processing_enabled": False,
}
with (root / "delivery.json").open("x") as handle:
    handle.write(json.dumps(out, indent=2) + "\n")
print(json.dumps(out, indent=2))
assert out["all_passed"], [key for key, passed in checks.items() if not passed]
