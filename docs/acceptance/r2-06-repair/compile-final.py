"""Compile append-only, read-only interpretation after independent basis review.

The original classification report, labels and first outputs are never rewritten.
No database, model, paid-entry or deployment operation is performed here.
"""

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

OUT = Path(__file__).parent


def read(name):
    return json.loads((OUT / name).read_text())


def sha(name):
    return hashlib.sha256((OUT / name).read_bytes()).hexdigest()


def write(name, value):
    with (OUT / name).open("x") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)


def ratio(numerator, denominator):
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": numerator / denominator if denominator else None,
    }


first = read("results-v1.json")
technical = read("technical-review-v3.json")
fee = read("fee-reconciliation.json")
pre = read("prepay-production.json")
post = read("final-production.json")
evaluation = read("final-evaluation.json")
production_window = read("production-fee-window.json")
regression = first["phases"]["regression"]
blind = first["phases"]["blind"]
pairs = {p["task_id"]: p for p in regression["candidate_results"]}
assert pairs[76]["applied"] and pairs[89]["applied"]
assert {p["task_id"] for p in pairs.values() if p["applied"]} == {76, 89}
assert pairs[76]["review"]["approved"] and pairs[89]["review"]["approved"]
assert 'The query mentions the "Wagner mercenary force"' in pairs[76]["raw_first"]["basis"]
assert regression["metrics"]["judgment_precision"]["numerator"] == 5
assert regression["metrics"]["judgment_precision"]["denominator"] == 7
assert first["overall_technical_pass"] is False
assert first["source_or_prompt_tuning_after_first_output"] is False
assert blind["started_queries"] == 1 and blind["registered_queries"] == 6
assert first["separate_review_challenges"]["physical_review_requests"] == 0
assert technical["strict_grounding_metrics"]["strictly_supported_final_member_coverage"] == ratio(1, 6)
assert technical["strict_grounding_metrics"]["all_invalid_applied_including_unsupported_basis"] == ratio(1, 2)
warm_queries = [json.loads(line) for line in (OUT / "regression-first-run.ndjson").read_text().splitlines() if json.loads(line)["event"] == "query"]
warm_occurrences = sum(len(q["vector_cache_before"]["warm_keys"]) for q in warm_queries)
warm_union = {key for q in warm_queries for key in q["vector_cache_before"]["warm_keys"]}
assert warm_occurrences == 89 and len(warm_union) == 19

label_metrics = [
    "candidate_recall", "candidate_recall_for_started_queries", "judgment_precision",
    "raw_accuracy", "schema_valid_first_outputs", "valid_reference_among_schema_valid",
    "raw_false_associations_among_negative_pairs",
]
result = {
    "schema_version": "r206-retest-results-v2-independent-basis-addendum",
    "at": datetime.now(UTC).isoformat(),
    "input_sha256": {name: sha(name) for name in [
        "results-v1.json", "technical-review-v3.json", "fee-reconciliation.json",
        "regression-first-run.ndjson", "blind-first-run.ndjson",
    ]},
    "interpretation": {
        "v1_classification_metrics_and_all_first_outputs_preserved": True,
        "v1_correct_applied_and_wrong_write_fields_only_compared_frozen_labels": True,
        "v2_strict_members_require_supported_basis_as_well_as_correct_label_and_references": True,
        "basis_failure_is_a_contract_failure_even_when_label_matches": True,
        "no_new_ground_truth_or_relabeling": True,
        "review_challenges_excluded_from_natural_metrics": True,
    },
    "regression": {
        "registered_queries": 12,
        "executed_queries": 11,
        "original_unavailable_query": 8877,
        "unavailable_is_not_model_failure_or_reassigned_split": True,
        "unchanged_label_metrics": {k: regression["metrics"][k] for k in label_metrics},
        "domain_sql32_valid_anchor_metadata12_pairs": regression["layers"],
        "selected_vector4_judgments": 40,
        "label_compatible_final_coverage": ratio(2, 6),
        "strict_supported_final_coverage": ratio(1, 6),
        "real_review_calls": 3,
        "real_cas_applied": 2,
        "strict_supported_applied": 1,
        "unrelated_topic_merges_among_applied": ratio(0, 2),
        "unrelated_topic_merges_among_attempted_negative_pairs": ratio(0, 34),
        "all_contract_invalid_writes_among_applied": ratio(1, 2),
        "review_rejections_among_reviews": ratio(1, 3),
        "unsupported_decision_review_interception": ratio(1, 2),
        "basis_invalid_among_approved_reviews": ratio(1, 2),
        "unsupported_reviewed_tasks": [69, 76],
        "review_rejected_judge_tasks": [69],
        "review_missed_unsupported_judge_tasks": [76],
        "strict_supported_applied_judge_tasks": [89],
        "citation_failures_judge_tasks": [54, 59, 64, 75],
        "additional_independent_basis_hallucination_judge_tasks": [105],
        "real_stale_cas_race_tested": False,
        "semantic_success_is_not_inferred_from_independent_label": True,
    },
    "blind": {
        "registered_queries": 6,
        "executed_queries": 1,
        "not_started_after_guard": 5,
        "registered_expected_association_pairs": 3,
        "unchanged_label_metrics": {k: blind["metrics"][k] for k in label_metrics},
        "domain_sql32_valid_anchor_metadata12_pairs": blind["layers"],
        "selected_vector4_judgments": 2,
        "strict_supported_final_coverage_registered_pairs": ratio(0, 3),
        "real_review_calls": 0,
        "real_cas_applied": 0,
        "wrong_writes_among_applied": ratio(0, 0),
        "review_interception": ratio(0, 0),
        "first_positive_basis_reviewed_as_supported": True,
        "basis_reviewed_judge_task": 108,
        "final_review_blocked_before_http_task": 110,
        "whole_blind_set_pass": False,
        "registration_loaded_for_reporting_only_after_guard_halt": True,
    },
    "combined_structural_legal_first_judgments": ratio(42, 42),
    "combined_visible_quote_voice_ownership_legal_first_judgments": ratio(38, 42),
    "costs": {
        "new_physical_requests": 48,
        "retries": 0,
        "new_known_usd": fee["new_known_usd"],
        "cumulative_r206_requests": 107,
        "cumulative_r206_known_usd": fee["cumulative_r206_known_usd"],
        "cold_vectors": first["cold_vector_cost_this_retest"],
        "warm_vectors": {
            "per_query_planned_version_lookup_occurrences": 89,
            "warm_lookup_occurrences": warm_occurrences,
            "distinct_reused_versions_across_queries": len(warm_union),
            "v1_unique_across_queries_field_was_sum_of_per_query_counts": True,
            "embedding_physical_requests": 0,
            "incremental_embedding_usd": "0",
            "historical_cache_build_cost_not_erased": True,
        },
        "real_review": regression["costs"]["topic_review"],
        "strict_supported_complete_query_chains": first["successful_complete_chains"],
        "complete_cold_success_chain": "unmeasured: blind review stopped at budget guard",
        "separate_review_cas_challenge": "unmeasured: no paid calls after guard",
    },
    "missing_real_dimensions": first["missing_real_dimensions"],
    "technical_gates": {
        "candidate_recall_min": 0.90,
        "association_precision_min": 0.95,
        "strict_final_correct_coverage_min": 0.80,
        "all_invalid_writes_max": 0,
        "required_real_dimensions_must_be_measured": True,
        "regression_precision_pass": False,
        "regression_strict_coverage_pass": False,
        "all_invalid_writes_zero_pass": False,
        "required_real_dimensions_pass": False,
    },
    "first_run_hashes": first["first_run_hashes"],
    "source_or_prompt_tuning_after_first_output": False,
    "new_paid_calls_for_this_report": 0,
    "database_writes": 0,
    "overall_technical_pass": False,
    "r206_complete": False,
    "user_acceptance": None,
    "production_enabled": False,
}

provider_delta = Decimal(str(post["provider"]["usage_monthly"])) - Decimal(str(pre["provider"]["usage_monthly"]))
production_delta = Decimal(post["known_ledger"][0]["known_usd"]) - Decimal(pre["known_ledger"][0]["known_usd"])
new_known = Decimal(fee["new_known_usd"])
assert provider_delta == new_known + production_delta
assert production_delta == Decimal(production_window["concurrent_known_usd"]) == 0
assert fee["original_seven_holds_unchanged"]
assert first["new_unresolved_holds"] == []
cap = Decimal("0.20")
cumulative = Decimal(fee["cumulative_r206_known_usd"])
next_hold = Decimal(first["blocked_before_http"][0]["next_full_reservation_usd"])
assert cumulative + next_hold > cap
fee_v2 = {
    "schema_version": "r206-retest-fee-addendum-v2",
    "at": datetime.now(UTC).isoformat(),
    "original_per_call_reconciliation_sha256": sha("fee-reconciliation.json"),
    "metadata_correction": {
        "original_field": "blind_unused_materials_opened",
        "meaning_in_v1_code": "blind registration was loaded for reporting after the executed prefix halted",
        "root_read_blind_materials_or_labels_during_fix": False,
        "registration_loaded_for_reporting_after_guard": True,
        "claim_remaining_queries_still_pristine_for_future_reuse": False,
    },
    "provider_monthly_usage_before_usd": str(pre["provider"]["usage_monthly"]),
    "provider_monthly_usage_after_usd": str(post["provider"]["usage_monthly"]),
    "provider_reading_delta_usd": str(provider_delta),
    "production_known_ledger_delta_usd": str(production_delta),
    "concurrent_r1_production_requests": len(production_window["concurrent_requests"]),
    "new_r206_known_usd": str(new_known),
    "provider_delta_exactly_reconciled": True,
    "new_r206_physical_requests": 48,
    "cumulative_r206_physical_requests": 107,
    "cumulative_r206_known_usd": str(cumulative),
    "original_pool_cap_usd": str(cap),
    "remaining_pool_usd": str(cap - cumulative),
    "next_original_full_review_reservation_usd": str(next_hold),
    "next_known_plus_hold_usd": str(cumulative + next_hold),
    "shortfall_usd": str(cumulative + next_hold - cap),
    "peak_actual_known_plus_complete_reservation_usd": fee["peak_known_plus_complete_next_reservation_usd"],
    "original_unknown_holds_count": 7,
    "original_unknown_holds_usd": "0.484867",
    "original_unknown_holds_unchanged": True,
    "new_unknown_or_active_holds": 0,
    "additional_discretionary_future_reserve_usd": "0",
    "every_new_call_still_requires_original_full_window_reservation": True,
    "evaluation_all_time_known_usd": evaluation["known_ledger"][0]["known_usd"],
    "evaluation_all_time_known_plus_old_holds_usd": "0.88559612",
    "original_evaluation_cap_usd": "1.50",
    "all_paid_calls_stopped_at_first_guard": True,
    "blocked_review_http_calls": 0,
    "old_reservations_released": False,
    "limits_or_prices_reset_or_weakened": False,
    "paid_requests_for_reconciliation": 0,
    "database_writes": 0,
}
write("results-v2.json", result)
write("fee-reconciliation-v2.json", fee_v2)
print(json.dumps({"strict_regression_coverage": result["regression"]["strict_supported_final_coverage"], "invalid_writes": result["regression"]["all_contract_invalid_writes_among_applied"], "provider_delta_usd": str(provider_delta), "shortfall_usd": fee_v2["shortfall_usd"], "technical_pass": False}, indent=2))
