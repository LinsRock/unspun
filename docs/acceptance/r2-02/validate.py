"""One-off deterministic R2-02 comparison; no database or provider calls."""

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import yaml
from unspun.core.content_reading import ContentInput
from unspun.pipeline.content_processing import processing_fingerprint

root = Path(__file__).resolve().parents[3]


def digest(data):
    return hashlib.sha256(data).hexdigest()


freeze = json.loads((root / "docs/evaluations/r2/freeze-v1.json").read_text())
checks = []
for entry in freeze["files"]:
    path = entry["path"]
    data = (root / path).read_bytes()
    revision = None
    if path == "config/sources.yml":
        revision = freeze["base_revision"]
        data = subprocess.check_output(["git", "show", f"{revision}:{path}"], cwd=root)
    assert digest(data) == entry["sha256"], path
    checks.append({"path": path, "sha256": entry["sha256"], "revision": revision})
inputs = json.loads((root / "docs/evaluations/r2/inputs-v1.json").read_text())
replayed = []
for candidate in inputs["candidates"]:
    content = ContentInput.model_validate(candidate["input"])
    assert (
        processing_fingerprint(content, "card")
        == candidate["card_processing_fingerprint"]
    )
    replayed.append(candidate["id"])
old_raw = subprocess.check_output(
    ["git", "show", "d4df296:config/sources.yml"], cwd=root
)
new_raw = (root / "config/sources.yml").read_bytes()
old, new = yaml.safe_load(old_raw), yaml.safe_load(new_raw)
quotas = {}
for before, after in zip(old["sources"], new["sources"], strict=True):
    without = dict(after)
    if after.get("r1", {}).get("quotas"):
        without["r1"] = dict(after["r1"])
        quotas[after["id"]] = without["r1"].pop("quotas")
    assert before == without, after["id"]
assert len(quotas) == 8
production = json.loads(
    (root / "docs/acceptance/r2-02/predeploy-production.json").read_text()
)
evaluation = json.loads(
    (root / "docs/acceptance/r2-02/predeploy-evaluation.json").read_text()
)
unit = (
    Decimal(production["budget"]["unit_costs"]["per_100_candidates"]["value_usd"]) / 100
)
remaining = Decimal(str(production["provider"]["limit_remaining"])) - Decimal("1.50")
result = {
    "schema_version": "r2-02-scan-comparison-v2",
    "checked_at": datetime.now(UTC).isoformat(),
    "base_revision": "d4df296",
    "reviewer_kind": "ai-technical",
    "comparison_kind": "Synthetic same-response engineering checks plus unchanged frozen contract replay; not historical list recall or new semantic evaluation.",
    "freeze_manifest_sha256": digest(
        (root / "docs/evaluations/r2/freeze-v1.json").read_bytes()
    ),
    "frozen_targets_verified": checks,
    "frozen_input_contract_and_processing_fingerprints_matched": replayed,
    "holdout_usage": "Deterministic contract/fingerprint replay only; no tuning or new labels.",
    "historical_pre_scan_counts": None,
    "user_ratings_and_omissions": "Preserved, missing values remain null.",
    "adapter_comparison": [
        {
            "adapter": adapter,
            "fixture": "server/tests/test_discovery_quotas.py::test_every_adapter_reports_pre_and_post_scan_counts_without_extra_requests",
            "list_entries": 4,
            "legacy_returned": 1,
            "v2_scanned": 3,
            "v2_valid": 3,
            "v2_distinct_identities": 2,
            "v2_duplicate_positions": 1,
            "v2_returned": 3 if adapter == "rss" else 2,
            "list_requests_per_poll_before_and_after": 2
            if adapter == "people_daily"
            else 1,
        }
        for adapter in (
            "rss",
            "zhihu_daily",
            "people_daily",
            "thepaper",
            "netease",
            "tencent",
        )
    ],
    "selection_comparison": {
        "fixture": "server/tests/test_discovery_quotas.py::test_seen_first_does_not_hide_new_identity_and_replay_keeps_one_receipt",
        "response_order": ["seen-first", "new-second", "duplicate-new-second"],
        "legacy_new_identities_visible_with_max_items_1": 0,
        "v2_new_identities_visible": 1,
        "v2_new_material_tasks": 1,
        "replay_new_tasks": 0,
        "paid_calls": 0,
    },
    "source_config": {
        "before_sha256": digest(old_raw),
        "after_sha256": digest(new_raw),
        "only_changes": quotas,
        "enabled_stages_scopes_periods_unchanged": True,
    },
    "daily_upper_bounds": {
        "metadata_positions_before": 144,
        "metadata_positions_after": 2580,
        "material_slots_before_and_after": 144,
        "new_card_slots_before_and_after": 144,
        "list_requests_before_and_after_excluding_retries_and_redirects": 98,
    },
    "cost_scenarios_usd": {
        "provider_observed_at": production["transaction"]["at"],
        "provider_remaining": str(production["provider"]["limit_remaining"]),
        "production_space_after_reserving_full_original_evaluation": str(remaining),
        "observed_attempted_candidate_unit": str(unit),
        "144_new_paid_candidates_per_day_at_observed_mean": str(unit * 144),
        "13_full_days_at_that_rate": str(unit * 144 * 13),
        "three_times_mean_for_13_days": str(unit * 144 * 13 * 3),
        "interpretation": "Card-only scenario, not a stable traffic or fee guarantee. Retry/unknown holds and guides still consume the original budget; high-cost scenarios defer under unchanged limits.",
        "evaluation_unknown_requests_retained": evaluation["budget"][
            "unresolved_calls"
        ],
        "evaluation_reserved_retained": evaluation["budget"]["reserved_usd"],
        "new_paid_evaluation_calls": 0,
    },
}
target = root / "docs/evaluations/r2/scan-comparison-v2.json"
target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
print(
    f"Verified {len(checks)} frozen targets, {len(replayed)} inputs and eight quota-only changes"
)
