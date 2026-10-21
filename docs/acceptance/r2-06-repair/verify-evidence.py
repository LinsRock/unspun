"""Read-only consistency checks and an append-only evidence manifest."""

import gzip
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

OUT = Path(__file__).parent.resolve()
ROOT = OUT.parents[2]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(name):
    return json.loads((OUT / name).read_text())


def write(name, value):
    with (OUT / name).open("x") as stream:
        json.dump(value, stream, indent=2)


checks = {}
freeze = json.loads((ROOT / "docs/evaluations/r2/member-repair-freeze-v1.json").read_text())
checks["frozen_103_source_config_registration_test_hashes"] = all(
    sha(ROOT / row["path"]) == row["sha256"] for row in freeze["files"]
) and len(freeze["files"]) == 103
review = read("technical-review-v3.json")
checks["independent_review_original_artifact_pins"] = all(
    sha(ROOT / row["path"]) == row["sha256"]
    for row in review["evidence_pins"] if row["path"].startswith("docs/")
)
result = read("results-v2.json")
checks["final_report_input_pins"] = all(
    sha(OUT / name) == digest for name, digest in result["input_sha256"].items()
)
checks["first_output_pins"] = all(
    sha(OUT / (phase + "-first-run.ndjson")) == digest
    for phase, digest in result["first_run_hashes"].items()
)
requests = json.loads(gzip.decompress((OUT / "physical-requests.json.gz").read_bytes()))
checks["all_48_real_request_responses_retained"] = len(requests) == 48 and all(
    row["response_payload"] and row["status"] == "responded" for row in requests
)
checks["blocked_review_has_no_request"] = all(row["task_id"] != 110 for row in requests)
checks["no_challenge_outputs_or_paid_requests"] = not (OUT / "challenge-first-run.ndjson").exists() and result["costs"]["new_physical_requests"] == 48
checks["strict_failure_and_empty_acceptance_preserved"] = (
    result["regression"]["strict_supported_final_coverage"]["numerator"] == 1
    and result["regression"]["all_contract_invalid_writes_among_applied"]["numerator"] == 1
    and result["regression"]["unsupported_decision_review_interception"]["denominator"] == 2
    and result["overall_technical_pass"] is False
    and result["production_enabled"] is False
    and result["user_acceptance"] is None
)
checks["engineering_delivery_separate_from_real_failure"] = (
    read("delivery.json")["all_delivery_integrity_checks_passed"] is True
    and read("delivery.json")["real_model_technical_pass"] is False
)
checks["provider_and_original_holds_reconciled"] = (
    read("fee-reconciliation-v2.json")["provider_delta_exactly_reconciled"] is True
    and read("fee-reconciliation-v2.json")["original_unknown_holds_unchanged"] is True
)
broken_links = []
for path in [OUT / "README.md", ROOT / "docs/acceptance/r2-06-repair-2026-10-21.md"]:
    for link in re.findall(r"\]\(([^)]+)\)", path.read_text()):
        if link.startswith(("https://", "http://", "#")):
            continue
        target = (path.parent / link.split("#", 1)[0]).resolve()
        if target == OUT / "evidence-manifest.json":
            continue
        if not target.exists():
            broken_links.append({"file": str(path.relative_to(ROOT)), "target": link})
checks["new_narrative_local_links_exist"] = not broken_links
secret_files = []
for path in OUT.rglob("*"):
    if not path.is_file():
        continue
    data = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
    if re.search(rb"sk-or-v1-[A-Za-z0-9]{20,}", data):
        secret_files.append(str(path.relative_to(ROOT)))
checks["no_provider_key_in_new_evidence_or_logs"] = not secret_files
assert all(checks.values()), {"checks": checks, "broken_links": broken_links, "secret_files": secret_files}
write("evidence-checks.json", {
    "at": datetime.now(UTC).isoformat(), "checks": checks,
    "all_passed": True, "paid_requests": 0, "database_writes": 0,
})
paths = sorted(path for path in OUT.rglob("*") if path.is_file() and path.name != "evidence-manifest.json")
paths += [ROOT / "docs/acceptance/r2-06-repair-2026-10-21.md"]
write("evidence-manifest.json", {
    "id": "r206-repair-delivery-evidence-v1", "at": datetime.now(UTC).isoformat(),
    "runtime_revision": "26ddfa20f69c0a26297a4202d146e2b45b670a79",
    "source_freeze_sha256": sha(ROOT / "docs/evaluations/r2/member-repair-freeze-v1.json"),
    "real_technical_pass": False, "production_enabled": False, "user_acceptance": None,
    "files": [{"path": str(path.relative_to(ROOT)), "sha256": sha(path), "bytes": path.stat().st_size} for path in paths],
})
print(json.dumps({"checks": checks, "artifacts": len(paths), "technical_pass": False}, indent=2))
