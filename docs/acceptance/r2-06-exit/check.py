"""Verify the frozen, unaccepted v6 snapshot without opening a paid entry.

Exit 2 means the recorded candidate remains unaccepted. Exit 3 means evidence
changed or is missing. This historical checker intentionally has no success or
execution path; a future real run needs its own reviewed evidence and authority.
"""

import gzip
import hashlib
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
DIRECTORY = "docs/acceptance/r2-06-exit"
INPUTS_SHA256 = "8eef129628a2eddff0829c17371ddc8b304396255213b989be9e6be992fd2e01"


def checked_bytes(root: Path, path: str, expected: str) -> bytes:
    content = (root / path).read_bytes()
    if hashlib.sha256(content).hexdigest() != expected:
        raise ValueError(f"frozen evidence changed: {path}")
    return content


def verify_snapshot(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = json.loads(checked_bytes(root, f"{DIRECTORY}/inputs.json", INPUTS_SHA256))
    evidence: dict[str, Any] = {}
    for name, ref in manifest["files"].items():
        content = checked_bytes(root, ref["path"], ref["sha256"])
        if ref["path"].endswith(".gz"):
            content = gzip.decompress(content)
        if not ref["path"].endswith(".ndjson"):
            evidence[name] = json.loads(content)
    for path, expected in evidence["sources"]["files"].items():
        checked_bytes(root, path, expected)

    contract = evidence["contract"]
    execution = evidence["execution"]
    delivery = evidence["delivery"]
    stop = evidence["paid_stop"]
    old_gate = evidence["old_gate"]
    if not (
        contract["contract"]["version"] == manifest["candidate_contract"]
        and delivery["production_revision"] == manifest["candidate_revision"]
        and execution["contract"] != contract["contract"]
        and stop["all_paid_phases_stopped"] is True
        and delivery["semantic_pass"] is False
        and evidence["offline"]["semantic_credit"] is False
        and delivery["user_acceptance"] is None
        and old_gate["first_output_sha256"] == manifest["files"]["first_outputs"]["sha256"]
        and old_gate["challenge_first_output_sha256"]
        == manifest["files"]["challenge_outputs"]["sha256"]
    ):
        raise ValueError("frozen snapshot is inconsistent")

    lookups = {row["id"]: row for row in evidence["provider_receipts"]["generation"]}
    receipt_gaps: dict[str, Any] = {
        "basis": "existing archived ledger snapshots; not a live balance or provider query",
        "provider_queries_performed": 0,
        "hold_action": "retain_full; no settlement or release",
        "required_receipt": (
            "Authoritative final cost/currency, including an explicit zero if applicable, "
            "bound to the original request and provider identity. A 404, missing ID, "
            "HTTP failure or aggregate balance delta is not such a receipt."
        ),
        "ledgers": {},
    }
    for name in ("evaluation", "production"):
        ledger = evidence[name]
        rows: list[dict[str, Any]] = []
        for row in ledger["unknown_requests"]:
            generation = row["provider_generation_id"]
            lookup = lookups.get(generation)
            rows.append(
                {
                    **row,
                    "last_archived_lookup": (
                        {"at": lookup["at"], "http_status": lookup["http_status"]}
                        if lookup
                        else None
                    ),
                    "receipt_gap": (
                        "lookup_404_not_a_cost_receipt"
                        if lookup
                        else "missing_generation_id"
                        if generation is None
                        else "not_queried_in_archived_audit"
                    ),
                }
            )
        receipt_gaps["ledgers"][name] = {
            "snapshot_at": ledger["completed_at"],
            "unresolved_count": len(rows),
            "held_usd": str(sum((Decimal(row["reserved_usd"]) for row in rows), Decimal(0))),
            "rows": rows,
        }

    result = {
        "verdict": "not_accepted",
        "exit_code": 2,
        "candidate": {
            "revision": manifest["candidate_revision"],
            "contract": manifest["candidate_contract"],
            "fingerprint": contract["fingerprint"],
            "runtime_source_files_verified": len(evidence["sources"]["files"]),
            "real_semantic_status": "unmeasured",
            "real_metrics": None,
            "engineering_pass_does_not_supply_semantic_evidence": True,
        },
        "last_real_run": {
            "contract": execution["contract"]["version"],
            "status": evidence["old_results"]["status"],
            "metrics": old_gate["metrics"],
            "real_challenges_pass": old_gate["real_challenges_pass"],
            "counts_as_current_candidate_evidence": False,
        },
        "frozen_population": evidence["exposed"]["counts"],
        "original_quality_gates": evidence["exposed"]["technical_gates"],
        "blockers": [
            "Unresolved fees have no authoritative per-request final cost receipts.",
            "Paid-stop remains; no separate explicit paid-resume authorization exists.",
            "The old v4 execution registration cannot run the v6 candidate.",
            "No real v6 exposed/challenge result; offline results earn no semantic credit.",
            "Independent blind and missing real dimensions remain unmeasured and out of scope.",
            "The admin correction checklist is unimplemented and out of scope.",
        ],
        "fee_snapshots": {
            name: {k: v for k, v in ledger.items() if k != "rows"}
            for name, ledger in receipt_gaps["ledgers"].items()
        },
        "same_pool": {
            "physical_requests": stop["batch"]["physical_requests"],
            "known_usd": evidence["ledger_audit"]["r206_pool_known_usd"],
            "unresolved_hold_usd": evidence["ledger_audit"]["new_eval_hold_usd"],
            "cap_usd": execution["budget"]["batch_limit_usd"],
            "evaluation_allocation_usd": execution["budget"]["original_evaluation_limit_usd"],
        },
        "r206_status": delivery["r206_status"],
        "user_acceptance": None,
        "automatic_next_action": None,
        "fresh_blind_preparation_authorized": False,
        "production_activation_authorized": False,
        "new_requests_or_database_writes": 0,
        "evidence_scope": "frozen local snapshot; no live production claim",
    }
    return result, receipt_gaps


def main() -> int:
    try:
        result, _ = verify_snapshot(ROOT)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"verdict": "evidence_error", "exit_code": 3, "reason": str(exc)}))
        return 3
    print(json.dumps(result, indent=2))
    return 2


if __name__ == "__main__":
    sys.exit(main())
