import copy
from datetime import timedelta
from typing import Any

import pytest

from tests.test_feed_ranking_evaluation import NOW, event_sample


def ready_suite() -> tuple[dict[str, Any], dict[str, Any]]:
    from dataclasses import asdict

    from unspun.evaluation.feed_ranking import DEFAULT_PARAMS
    from unspun.evaluation.feed_suite import candidate_source_hash, content_hash

    snapshot: dict[str, Any] = {
        "provenance": "production-read-only-snapshot",
        "captured_at": NOW.isoformat(),
        "event_count": 30,
        "events": [event_sample(i, [("a", NOW - timedelta(hours=i))]) for i in range(1, 31)],
    }
    annotations: dict[str, Any] = {
        "version": "synthetic-test-reviewed-v1",
        "snapshot_sha256": content_hash(snapshot),
        "frozen": True,
        "parameters_sha256": content_hash(asdict(DEFAULT_PARAMS)),
        "candidate_source_sha256": candidate_source_hash(),
        "reviewed_by": "synthetic-test-reviewer",
        "reviewed_at": NOW.isoformat(),
        "coverage_reviewed": True,
        "coverage_notes": "Synthetic controls for readiness behavior only.",
        "labels": [
            {
                "event_id": i,
                "domain": ["science", "economics", "world"][i % 3],
                "importance_band": 3,
                "worth_reading": True,
                "timestamp_review": {str(i * 100): "valid"},
                "publisher_groups": {"a": "media-a"},
                "reprints_reviewed": True,
                "known_reprints": [],
                "reviewed_by": "synthetic-test-reviewer",
                "reviewed_at": NOW.isoformat(),
            }
            for i in range(1, 31)
        ],
        "expected_pairs": [
            {
                "sort": sort,
                "range": "all",
                "before_event_id": 1,
                "after_event_id": 2,
                "reason": "Synthetic ordering control.",
                "reviewed_by": "synthetic-test-reviewer",
                "reviewed_at": NOW.isoformat(),
            }
            for sort in ("newest", "hot", "important")
        ],
    }
    refreeze(annotations)
    return snapshot, annotations


def refreeze(annotations: dict[str, Any]) -> None:
    from unspun.evaluation.feed_suite import content_hash

    annotations["frozen_sha256"] = content_hash(
        {k: v for k, v in annotations.items() if k != "frozen_sha256"}
    )


def evaluate(snapshot: dict[str, Any], annotations: dict[str, Any]) -> dict[str, Any]:
    from unspun.evaluation.feed_suite import evaluate_suite

    return evaluate_suite(snapshot, annotations)


def test_draft_is_not_a_pass_and_lists_missing_human_inputs() -> None:
    snapshot, annotations = ready_suite()
    annotations["frozen"] = False
    annotations["reviewed_by"] = None
    annotations["labels"][0]["importance_band"] = None
    annotations["labels"][0]["worth_reading"] = None
    report = evaluate(snapshot, annotations)
    assert report["ready"] is False
    assert report["passed"] is False
    assert any("importance" in issue for issue in report["readiness_issues"])
    assert any("frozen" in issue for issue in report["readiness_issues"])
    assert report["hashes"]["snapshot"] == annotations["snapshot_sha256"]


def test_reviewed_frozen_suite_passes_and_preserves_old_baseline() -> None:
    snapshot, annotations = ready_suite()
    report = evaluate(snapshot, annotations)
    assert report["ready"] is True
    assert report["passed"] is True
    assert report["pair_results"][0]["passed"] is True
    assert len(report["rankings"]["all"]["baseline"]) == 30
    assert len(report["rankings"]["all"]["activity"]) == 24
    assert set(report["hashes"]) >= {"snapshot", "annotations", "parameters", "source"}


@pytest.mark.parametrize("count", [29, 51])
def test_size_outside_30_to_50_is_not_ready(count: int) -> None:
    from unspun.evaluation.feed_suite import content_hash

    snapshot, annotations = ready_suite()
    snapshot["events"] = [event_sample(i, [("a", NOW)]) for i in range(1, count + 1)]
    annotations["snapshot_sha256"] = content_hash(snapshot)
    report = evaluate(snapshot, annotations)
    assert report["ready"] is False
    assert any("30" in issue and "50" in issue for issue in report["readiness_issues"])


@pytest.mark.parametrize(
    "field,value",
    [
        ("provenance", "synthetic"),
        ("captured_at", "2026-10-14T01:00:00"),
    ],
)
def test_invalid_snapshot_is_not_ready(field: str, value: str) -> None:
    snapshot, annotations = ready_suite()
    snapshot[field] = value
    report = evaluate(snapshot, annotations)
    assert report["ready"] is False
    assert report["passed"] is False


def test_duplicate_event_or_member_article_is_not_ready() -> None:
    snapshot, annotations = ready_suite()
    snapshot["events"][1] = copy.deepcopy(snapshot["events"][0])
    report = evaluate(snapshot, annotations)
    assert report["ready"] is False
    assert any("duplicate event" in issue for issue in report["readiness_issues"])
    snapshot, annotations = ready_suite()
    snapshot["events"][1]["articles"][0]["id"] = 100
    assert any(
        "duplicate article" in issue
        for issue in evaluate(snapshot, annotations)["readiness_issues"]
    )


def test_snapshot_hash_mismatch_cannot_pass() -> None:
    snapshot, annotations = ready_suite()
    snapshot["events"][0]["title"] = "changed after annotation"
    report = evaluate(snapshot, annotations)
    assert report["passed"] is False
    assert any("hash" in issue for issue in report["readiness_issues"])


@pytest.mark.parametrize(
    "field,value",
    [
        ("publisher_groups", {}),
        ("timestamp_review", {}),
        ("reviewed_by", "  "),
        ("reviewed_at", "2026-10-14T01:00:00"),
        ("reprints_reviewed", False),
        ("worth_reading", None),
        ("importance_band", None),
    ],
)
def test_incomplete_event_annotation_cannot_pass(field: str, value: Any) -> None:
    snapshot, annotations = ready_suite()
    annotations["labels"][0][field] = value
    assert evaluate(snapshot, annotations)["passed"] is False


def test_conflicting_media_groups_are_not_ready() -> None:
    snapshot, annotations = ready_suite()
    annotations["labels"][0]["publisher_groups"] = {"a": "another-media"}
    report = evaluate(snapshot, annotations)
    assert any("conflicting publisher" in issue for issue in report["readiness_issues"])


def test_reviewed_time_disagrees_with_candidate_rule_requires_resolution() -> None:
    snapshot, annotations = ready_suite()
    annotations["labels"][0]["timestamp_review"]["100"] = "anomalous"
    report = evaluate(snapshot, annotations)
    assert report["passed"] is False
    assert any("timestamp classification" in issue for issue in report["readiness_issues"])


def test_missing_sort_pair_and_foreign_pair_are_not_ready() -> None:
    snapshot, annotations = ready_suite()
    annotations["expected_pairs"] = annotations["expected_pairs"][:1]
    assert evaluate(snapshot, annotations)["ready"] is False
    snapshot, annotations = ready_suite()
    annotations["expected_pairs"][0]["after_event_id"] = 999
    assert evaluate(snapshot, annotations)["ready"] is False


def test_pair_failure_is_retained_as_a_failure() -> None:
    snapshot, annotations = ready_suite()
    annotations["expected_pairs"][0]["before_event_id"] = 2
    annotations["expected_pairs"][0]["after_event_id"] = 1
    refreeze(annotations)
    report = evaluate(snapshot, annotations)
    assert report["ready"] is True
    assert report["passed"] is False
    assert report["pair_results"][0]["passed"] is False


def test_pair_with_candidate_excluded_event_is_failure() -> None:
    snapshot, annotations = ready_suite()
    annotations["expected_pairs"][1]["before_event_id"] = 30
    refreeze(annotations)
    report = evaluate(snapshot, annotations)
    assert report["ready"] is True
    assert report["passed"] is False
    assert report["pair_results"][1]["reason"] == "event outside candidate window"


def test_reprint_references_must_belong_to_reviewed_event() -> None:
    snapshot, annotations = ready_suite()
    annotations["labels"][0]["known_reprints"] = [
        {"article_id": 999, "original_url": "https://example.com/original"}
    ]
    report = evaluate(snapshot, annotations)
    assert report["ready"] is False


def test_duplicate_or_extra_labels_are_not_accepted() -> None:
    snapshot, annotations = ready_suite()
    annotations["labels"].append(copy.deepcopy(annotations["labels"][0]))
    assert evaluate(snapshot, annotations)["ready"] is False
    snapshot, annotations = ready_suite()
    annotations["labels"][0]["event_id"] = 999
    assert evaluate(snapshot, annotations)["ready"] is False


def test_three_domains_and_explicit_coverage_review_are_required() -> None:
    snapshot, annotations = ready_suite()
    for label in annotations["labels"]:
        label["domain"] = "world"
    assert evaluate(snapshot, annotations)["ready"] is False
    snapshot, annotations = ready_suite()
    annotations["coverage_reviewed"] = False
    assert evaluate(snapshot, annotations)["ready"] is False


def test_cli_strict_draft_and_malformed_input(tmp_path: Any) -> None:
    import json

    from unspun.evaluation.run_feed_ranking import main

    snapshot, annotations = ready_suite()
    annotations["frozen"] = False
    sp = tmp_path / "snapshot.json"
    ap = tmp_path / "annotations.json"
    output = tmp_path / "report.json"
    sp.write_text(json.dumps(snapshot, default=str))
    ap.write_text(json.dumps(annotations))
    args = ["--snapshot", str(sp), "--annotations", str(ap), "--output", str(output)]
    assert main(args) == 1
    assert json.loads(output.read_text())["passed"] is False
    assert main([*args, "--draft"]) == 0
    assert json.loads(output.read_text())["passed"] is False
    sp.write_text("invalid JSON")
    assert main(args) == 2
    assert json.loads(output.read_text())["passed"] is False


def test_frozen_annotations_must_match_the_recorded_hash() -> None:
    snapshot, annotations = ready_suite()
    annotations["labels"][0]["worth_reading"] = False
    report = evaluate(snapshot, annotations)
    assert report["ready"] is False
    assert any("frozen annotation hash" in issue for issue in report["readiness_issues"])


def test_draft_cli_cannot_claim_a_pass_even_for_reviewed_inputs(tmp_path: Any) -> None:
    import json

    from unspun.evaluation.run_feed_ranking import main

    snapshot, annotations = ready_suite()
    sp = tmp_path / "snapshot.json"
    ap = tmp_path / "annotations.json"
    output = tmp_path / "report.json"
    sp.write_text(json.dumps(snapshot, default=lambda value: value.isoformat()))
    ap.write_text(json.dumps(annotations))
    args = ["--snapshot", str(sp), "--annotations", str(ap), "--output", str(output)]
    assert main(args) == 0
    assert json.loads(output.read_text())["passed"] is True
    assert main([*args, "--draft"]) == 0
    report = json.loads(output.read_text())
    assert report["ready"] is True
    assert report["passed"] is False


def test_cli_cannot_overwrite_input(tmp_path: Any) -> None:
    from unspun.evaluation.run_feed_ranking import main

    sp = tmp_path / "snapshot.json"
    sp.write_text("original input")
    with pytest.raises(SystemExit) as error:
        main(
            ["--snapshot", str(sp), "--annotations", str(tmp_path / "a.json"), "--output", str(sp)]
        )
    assert error.value.code == 2
    assert sp.read_text() == "original input"


def test_changed_candidate_parameters_require_review() -> None:
    from unspun.evaluation.feed_ranking import CandidateParams
    from unspun.evaluation.feed_suite import evaluate_suite

    snapshot, annotations = ready_suite()
    report = evaluate_suite(snapshot, annotations, CandidateParams(half_life_hours=48))
    assert report["ready"] is False
    assert any("parameter hash" in issue for issue in report["readiness_issues"])


def test_changed_candidate_source_requires_review() -> None:
    snapshot, annotations = ready_suite()
    annotations["candidate_source_sha256"] = "previous-code-version"
    refreeze(annotations)
    report = evaluate(snapshot, annotations)
    assert report["ready"] is False
    assert any("source hash" in issue for issue in report["readiness_issues"])


def test_snapshot_records_baseline_half_life_separately() -> None:
    from unspun.evaluation.feed_suite import content_hash

    snapshot, annotations = ready_suite()
    snapshot["baseline_half_life_hours"] = 48
    snapshot["events"][0]["changed_at"] = NOW - timedelta(hours=24)
    annotations["snapshot_sha256"] = content_hash(snapshot)
    refreeze(annotations)
    rows = evaluate(snapshot, annotations)["rankings"]["all"]["baseline"]
    first = next(row for row in rows if row["id"] == 1)
    assert first["metric"] == pytest.approx(50 * 2 ** (-24 / 48))


def test_reviewed_article_publishers_override_aggregator_source_group() -> None:
    from unspun.evaluation.feed_suite import content_hash

    snapshot, annotations = ready_suite()
    snapshot["events"][0]["articles"].append({**snapshot["events"][0]["articles"][0], "id": 101})
    label = annotations["labels"][0]
    label["timestamp_review"]["101"] = "valid"
    label["publisher_groups"] = {"a": "media-a"}
    label["article_publisher_groups"] = {"100": "publisher-a", "101": "publisher-b"}
    annotations["snapshot_sha256"] = content_hash(snapshot)
    refreeze(annotations)
    report = evaluate(snapshot, annotations)
    assert report["ready"] is True
    row = next(r for r in report["rankings"]["all"]["hot"] if r["id"] == 1)
    assert row["active_publishers"] == 2


def test_article_publisher_group_cannot_reference_foreign_article() -> None:
    snapshot, annotations = ready_suite()
    annotations["labels"][0]["article_publisher_groups"] = {"999": "foreign"}
    refreeze(annotations)
    report = evaluate(snapshot, annotations)
    assert report["ready"] is False
    assert any("article publisher" in issue for issue in report["readiness_issues"])


def technical_suite() -> tuple[dict[str, Any], dict[str, Any]]:
    snapshot, annotations = ready_suite()
    annotations["reviewer_kind"] = "ai-technical"
    annotations["technical_review_origin"] = "User authorized original-time and grouping checks."
    for label in annotations["labels"]:
        label["reviewer_kind"] = "ai-technical"
        label["subjective_labels_origin"] = "User supplied importance and worth-reading grades."
    for pair in annotations["expected_pairs"]:
        pair["reviewer_kind"] = "ai-technical"
    refreeze(annotations)
    return snapshot, annotations


def test_ai_technical_review_records_user_subjective_origin_and_role() -> None:
    snapshot, annotations = technical_suite()
    report = evaluate(snapshot, annotations)
    assert report["ready"] is True
    assert report["passed"] is True
    assert report["publisher_grouping"] == "ai-technical-reviewed"
    assert report["reviewer_kind"] == "ai-technical"
    assert report["pair_results"][0]["reviewer_kind"] == "ai-technical"


@pytest.mark.parametrize("origin", [None, "", "   "])
def test_ai_technical_review_requires_technical_origin(origin: Any) -> None:
    snapshot, annotations = technical_suite()
    annotations["technical_review_origin"] = origin
    refreeze(annotations)
    assert evaluate(snapshot, annotations)["ready"] is False


@pytest.mark.parametrize("origin", [None, "", "   "])
def test_ai_technical_label_requires_original_user_grades_origin(origin: Any) -> None:
    snapshot, annotations = technical_suite()
    annotations["labels"][0]["subjective_labels_origin"] = origin
    refreeze(annotations)
    assert evaluate(snapshot, annotations)["ready"] is False


def test_technical_review_preserves_all_existing_readiness_gates() -> None:
    snapshot, annotations = technical_suite()
    annotations["coverage_reviewed"] = False
    annotations["labels"][0]["importance_band"] = None
    annotations["labels"][0]["reviewed_at"] = None
    refreeze(annotations)
    report = evaluate(snapshot, annotations)
    assert report["ready"] is False
    assert any("coverage" in issue for issue in report["readiness_issues"])
    assert any("importance_band" in issue for issue in report["readiness_issues"])
    assert any("reviewed_at" in issue for issue in report["readiness_issues"])
    assert not any("human" in issue for issue in report["readiness_issues"])


def test_legacy_review_defaults_to_human() -> None:
    snapshot, annotations = ready_suite()
    report = evaluate(snapshot, annotations)
    assert report["ready"] is True
    assert report["reviewer_kind"] == "human"
    assert report["publisher_grouping"] == "human-reviewed"
    assert report["pair_results"][0]["reviewer_kind"] == "human"


@pytest.mark.parametrize(
    "precision,classification", [("unknown", "missing"), ("date", "valid"), ("time", "anomalous")]
)
def test_timestamp_review_uses_original_publication_not_feed_time(
    precision: str, classification: str
) -> None:
    import json

    from unspun.evaluation.feed_suite import content_hash

    snapshot, annotations = technical_suite()
    article = snapshot["events"][0]["articles"][0]
    article["reported_precision"] = precision
    article["reported_date"] = (NOW - timedelta(days=1)).date()
    article["reported_at"] = NOW + timedelta(days=1)
    annotations["labels"][0]["timestamp_review"]["100"] = classification
    annotations["snapshot_sha256"] = content_hash(snapshot)
    refreeze(annotations)
    report = evaluate(snapshot, annotations)
    assert report["ready"] is True
    json.dumps(report)


def test_candidate_hash_covers_publication_and_public_impact_sources(monkeypatch: Any) -> None:
    from pathlib import Path

    from unspun.evaluation.feed_suite import candidate_source_hash

    original = Path.read_bytes
    baseline = candidate_source_hash()
    for filename in ("publication.py", "public_impact.py"):

        def modified(path: Path, target: str = filename) -> bytes:
            return original(path) + (b" changed" if path.name == target else b"")

        with monkeypatch.context() as patch:
            patch.setattr(Path, "read_bytes", modified)
            assert candidate_source_hash() != baseline


@pytest.mark.parametrize("excerpt", [None, "Unrelated product release body."])
def test_public_impact_promotion_requires_quote_in_original_body(excerpt: Any) -> None:
    from unspun.evaluation.feed_suite import content_hash

    snapshot, annotations = technical_suite()
    event = snapshot["events"][0]
    event["articles"][0]["impact_original_excerpt"] = excerpt
    event["public_impact_status"] = "supported"
    event["public_impact_urgent"] = True
    event["public_impact_evidence"] = [
        {"article_id": 100, "quote": "Emergency evacuation ordered."}
    ]
    annotations["snapshot_sha256"] = content_hash(snapshot)
    refreeze(annotations)
    report = evaluate(snapshot, annotations)
    assert report["ready"] is False
    assert any("original excerpt" in issue for issue in report["readiness_issues"])


def test_source_grounded_public_impact_promotion_is_ready() -> None:
    from unspun.evaluation.feed_suite import content_hash

    snapshot, annotations = technical_suite()
    event = snapshot["events"][0]
    event["articles"][0]["impact_original_excerpt"] = (
        "Emergency evacuation ordered. Roads are closed."
    )
    event["public_impact_status"] = "supported"
    event["public_impact_urgent"] = True
    event["public_impact_evidence"] = [
        {"article_id": 100, "quote": "Emergency evacuation ordered."}
    ]
    annotations["snapshot_sha256"] = content_hash(snapshot)
    refreeze(annotations)
    assert evaluate(snapshot, annotations)["ready"] is True


def test_unknown_public_impact_remains_an_accepted_fallback() -> None:
    from unspun.evaluation.feed_suite import content_hash

    snapshot, annotations = technical_suite()
    snapshot["events"][0]["public_impact_status"] = "unknown"
    annotations["snapshot_sha256"] = content_hash(snapshot)
    refreeze(annotations)
    assert evaluate(snapshot, annotations)["ready"] is True
