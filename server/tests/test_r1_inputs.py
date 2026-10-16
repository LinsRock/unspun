import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from unspun.evaluation.r1_inputs import inspect_registry, main, read_object

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = Path("docs/evaluations/r1/inputs-v1.json")


@pytest.fixture
def evidence_root(tmp_path: Path) -> Path:
    registry = read_object(ROOT / REGISTRY)
    for entry in registry["files"]:
        target = tmp_path / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / entry["path"], target)
    (tmp_path / REGISTRY).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / REGISTRY, tmp_path / REGISTRY)
    return tmp_path


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def exported_feedback() -> dict[str, Any]:
    source = ROOT / "docs/research/r0-2026-10-15/candidates.json"
    candidates = read_object(source)["candidates"]
    empty = {
        "worth_reading_now": None,
        "importance_1_to_5": None,
        "interest_1_to_5": None,
        "place": None,
        "reason": None,
        "interest": None,
    }
    # Synthetic test input only, never imported into the registered evidence.
    reviews = {"C01": {**empty, "worth_reading_now": "no", "importance_1_to_5": 1}}
    return {
        "schema_version": "unspun-r0-reading-feedback-v1",
        "dataset_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "contents": reviews,
        "topics": {},
        "experience": {"density": "compact"},
        "updated_at": "2026-10-16T04:00:00Z",
        "exported_at": "2026-10-16T04:01:00Z",
        "reference_date": "2026-10-15",
        "layout_schema": "unspun-r0-reading-layout-v1",
        "selection_version": "early",
        "ranking_method": "manual_layout_for_review_not_algorithm_evaluation",
        "reviewed_content_count": 1,
        "candidates": [
            {
                **{
                    key: candidate[key]
                    for key in (
                        "id",
                        "title",
                        "url",
                        "publication",
                        "material_status",
                        "material_sha256",
                    )
                },
                "human_review": reviews.get(candidate["id"], empty),
            }
            for candidate in candidates
        ],
    }


def test_real_registration_preserves_unknowns_and_does_not_unlock_g1() -> None:
    report = inspect_registry(ROOT, ROOT / REGISTRY)
    assert report["registration_valid"] is True
    assert report["technical_ready"] is False
    assert report["user_quality_passed"] is None
    assert report["feedback"]["status"] == "not_provided"
    assert report["feedback"]["reviews"] == {}
    assert report["candidate_count"] == 43
    assert report["source_count_with_samples"] == 17
    assert report["observation_count"] == 232
    assert report["material_fingerprint_count"] == 39
    assert report["missing_material_fingerprints"] == ["C30", "C38", "C39", "C40"]
    assert report["body_availability_checked"] is False
    assert report["legacy"]["event_count"] == 40
    assert report["legacy"]["article_count"] == 53
    assert report["legacy"]["worth_reading_true"] == 32
    assert report["legacy"]["worth_reading_false"] == 8
    assert report["legacy"]["ranking_regression_executed"] is False


def test_source_drift_is_rejected_before_reporting_readiness(evidence_root: Path) -> None:
    path = evidence_root / "docs/research/r0-2026-10-15/candidates.json"
    path.write_text(path.read_text() + "\n")
    with pytest.raises(ValueError, match="fingerprint changed"):
        inspect_registry(evidence_root, evidence_root / REGISTRY)


def test_legacy_labels_are_compared_even_if_file_pin_is_updated(evidence_root: Path) -> None:
    registry = read_object(evidence_root / REGISTRY)
    entry = next(item for item in registry["files"] if item["role"] == "legacy_technical_labels")
    path = evidence_root / entry["path"]
    document = read_object(path)
    document["labels"][0]["importance_band"] = 5
    write_json(path, document)
    entry["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    write_json(evidence_root / REGISTRY, registry)
    with pytest.raises(ValueError, match="subjective labels changed"):
        inspect_registry(evidence_root, evidence_root / REGISTRY)


@pytest.mark.parametrize("change", ["duplicate_pin", "missing_boundary", "outside_repository"])
def test_registry_cannot_silently_drop_or_redirect_evidence(
    evidence_root: Path, change: str
) -> None:
    path = evidence_root / REGISTRY
    registry = read_object(path)
    if change == "duplicate_pin":
        registry["candidates"].append(registry["candidates"][0])
    elif change == "missing_boundary":
        registry["boundaries"]["stale_news_regression"].append("C99")
    else:
        registry["files"][0]["path"] = "../../outside.json"
    write_json(path, registry)
    with pytest.raises(ValueError):
        inspect_registry(evidence_root, path)


def test_feedback_preserves_actual_fields_and_empty_values_without_quality_claims(
    tmp_path: Path,
) -> None:
    feedback = tmp_path / "test-feedback.json"
    write_json(feedback, exported_feedback())
    report = inspect_registry(ROOT, ROOT / REGISTRY, feedback)
    imported = report["feedback"]
    assert imported["content_count_with_any_input"] == 1
    assert imported["reviews"]["C01"]["importance_1_to_5"] == 1
    assert imported["reviews"]["C01"]["interest_1_to_5"] is None
    assert "C02" not in imported["reviews"]
    assert imported["identity_verified"] is False
    assert imported["quality_passed"] is None
    assert report["technical_ready"] is False
    assert report["user_quality_passed"] is None


@pytest.mark.parametrize(
    "change",
    [
        "dataset_hash",
        "provenance",
        "duplicate_candidate",
        "conflicting_reviews",
        "unknown_target",
        "invalid_score",
        "bool_score",
        "wrong_count",
        "naive_timestamp",
        "unknown_field",
    ],
)
def test_feedback_rejects_corruption_instead_of_coercing_user_judgments(
    tmp_path: Path, change: str
) -> None:
    document = exported_feedback()
    if change == "dataset_hash":
        document["dataset_sha256"] = "0" * 64
    elif change == "provenance":
        document["candidates"][0]["url"] = "https://example.com/different"
    elif change == "duplicate_candidate":
        document["candidates"].append(document["candidates"][0])
    elif change == "conflicting_reviews":
        document["candidates"][0]["human_review"] = {}
    elif change == "unknown_target":
        document["contents"]["C99"] = {"reason": "Unknown content"}
    elif change in {"invalid_score", "bool_score"}:
        document["contents"]["C01"]["importance_1_to_5"] = 6 if change == "invalid_score" else True
    elif change == "wrong_count":
        document["reviewed_content_count"] = 43
    elif change == "naive_timestamp":
        document["exported_at"] = "2026-10-16T04:00:00"
    else:
        document["contents"]["C01"]["guessed_score"] = 5
    feedback = tmp_path / "test-feedback.json"
    write_json(feedback, document)
    with pytest.raises(ValueError):
        inspect_registry(ROOT, ROOT / REGISTRY, feedback)


def test_cli_preparation_success_does_not_mean_technical_readiness(tmp_path: Path) -> None:
    arguments = ["--root", str(ROOT), "--registry", str(ROOT / REGISTRY)]
    assert main([*arguments, "--output", str(tmp_path / "registration.json")]) == 0
    gated = tmp_path / "technical-gate.json"
    assert main([*arguments, "--output", str(gated), "--require-technical-ready"]) == 1
    assert read_object(gated)["technical_ready"] is False
    before = (ROOT / REGISTRY).read_bytes()
    with pytest.raises(SystemExit):
        main([*arguments, "--output", str(ROOT / REGISTRY)])
    assert (ROOT / REGISTRY).read_bytes() == before


def test_cli_keeps_invalid_input_report_without_passing(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{}")
    output = tmp_path / "invalid-report.json"
    assert main(["--root", str(ROOT), "--registry", str(invalid), "--output", str(output)]) == 2
    report = read_object(output)
    assert report["registration_valid"] is False
    assert report["technical_ready"] is False
    assert report["user_quality_passed"] is None
