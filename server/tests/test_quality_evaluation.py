from typing import Any

from unspun.evaluation.quality import evaluate_output, load_cases


def case() -> dict[str, Any]:
    return {
        "id": "sample",
        "articles": [
            {"id": 1, "title": "Bridge opens", "content": "A bridge reopened at 11:00."},
            {"id": 2, "title": "Traffic resumes", "content": "Traffic resumed at 11:00."},
        ],
        "expectations": {
            "min_claims": 2,
            "allowed_kinds": ["temporal_update"],
            "forbidden_patterns": ["2023"],
        },
    }


def test_metrics_distinguish_valid_evidence_from_foreign_quote() -> None:
    output = {
        "claims": [
            {
                "article_id": 1,
                "claim": "Bridge reopened",
                "evidence_quote": "A bridge reopened at 11:00.",
            },
            {
                "article_id": 2,
                "claim": "Traffic resumed",
                "evidence_quote": "A bridge reopened at 11:00.",
            },
        ],
        "disagreements": [],
    }
    metrics = evaluate_output(case(), output)
    assert metrics["valid_evidence_claims"] == 1
    assert metrics["claim_count"] == 2
    assert metrics["passed"] is False


def test_all_rejected_does_not_pass_a_normal_case() -> None:
    metrics = evaluate_output(case(), {"claims": [], "disagreements": []})
    assert metrics["minimum_coverage_met"] is False
    assert metrics["passed"] is False


def test_valid_empty_comparison_is_allowed_only_for_insufficient_input() -> None:
    item = case()
    item["expectations"]["min_claims"] = 0
    assert evaluate_output(item, {"claims": [], "disagreements": []})["passed"] is True


def test_expected_kind_and_invented_assertion_are_separate_metrics() -> None:
    output = {
        "claims": [
            {
                "article_id": 1,
                "claim": "Opened in 2023",
                "evidence_quote": "A bridge reopened at 11:00.",
            },
            {
                "article_id": 2,
                "claim": "Traffic resumed",
                "evidence_quote": "Traffic resumed at 11:00.",
            },
        ],
        "disagreements": [
            {"point": "The reports conflict", "claim_indexes": [0, 1], "kind": "factual_conflict"}
        ],
    }
    metrics = evaluate_output(case(), output)
    assert metrics["forbidden_assertions"] == ["2023"]
    assert metrics["unexpected_kinds"] == ["factual_conflict"]
    assert metrics["passed"] is False


def test_fixed_case_set_has_thirty_cases_and_identifies_synthetic_controls() -> None:
    cases = load_cases()
    assert len(cases) == 30
    assert sum(item["provenance"] == "production-audit-excerpt" for item in cases) == 5
    assert sum(item["provenance"] == "synthetic-control" for item in cases) == 25


def test_duplicate_claims_cannot_satisfy_source_coverage() -> None:
    claim = {
        "article_id": 1,
        "claim": "Bridge reopened",
        "evidence_quote": "A bridge reopened at 11:00.",
    }
    metrics = evaluate_output(case(), {"claims": [claim, claim], "disagreements": []})
    assert metrics["minimum_coverage_met"] is False
    assert metrics["passed"] is False


def test_relation_indices_are_checked_against_retained_claims() -> None:
    output = {
        "claims": [
            {
                "article_id": 1,
                "claim": "Bridge reopened",
                "evidence_quote": "A bridge reopened at 11:00.",
            },
            {
                "article_id": 2,
                "claim": "Traffic resumed",
                "evidence_quote": "Traffic resumed at 11:00.",
            },
        ],
        "disagreements": [
            {"kind": "temporal_update", "point": "Updated", "claim_indexes": [0, 99]}
        ],
    }
    assert evaluate_output(case(), output)["invalid_relations"] == 1


def test_missing_genuine_conflict_cannot_pass_by_omitting_relations() -> None:
    item = case()
    item["expectations"]["required_kinds"] = ["factual_conflict"]
    output = {
        "claims": [
            {
                "article_id": 1,
                "claim": "Bridge reopened",
                "evidence_quote": "A bridge reopened at 11:00.",
            },
            {
                "article_id": 2,
                "claim": "Traffic resumed",
                "evidence_quote": "Traffic resumed at 11:00.",
            },
        ],
        "disagreements": [],
    }
    assert evaluate_output(item, output)["missing_required_kinds"] == ["factual_conflict"]


def test_summary_errors_cannot_hide_behind_valid_comparison() -> None:
    item = case()
    output: dict[str, Any] = {"claims": [], "disagreements": []}
    item["expectations"]["min_claims"] = 0
    metrics = evaluate_output(
        item,
        output,
        summaries=[{"article_id": 1, "summary": "Opened in 2023", "title_zh": "Opened"}],
    )
    assert metrics["summary_forbidden_assertions"] == ["2023"]
    assert metrics["passed"] is False


def test_per_article_retention_includes_summary_and_title() -> None:
    item = case()
    item["expectations"]["min_claims"] = 0
    item["expectations"]["summary_required_patterns"] = {"1": ["11:00"]}
    metrics = evaluate_output(
        item,
        {"claims": [], "disagreements": []},
        summaries=[{"article_id": 1, "summary": "Bridge reopened"}],
    )
    assert metrics["summary_missing_required_facts"] == ["1:11:00"]
    assert metrics["passed"] is False
