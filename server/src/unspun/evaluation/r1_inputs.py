"""Register R1 evidence offline without claiming a technical or user quality pass."""

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

SHA256 = r"^[0-9a-f]{64}$"
REVIEW_FIELDS = ("worth_reading_now", "importance_1_to_5", "interest_1_to_5", "place", "reason")
EXPERIENCE_FIELDS = {
    "density",
    "selection_limit",
    "refresh_preference",
    "notes",
    "missing",
    "update_assessment",
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PinnedFile(StrictModel):
    role: str
    path: str
    sha256: str = Field(pattern=SHA256)


class CandidatePin(StrictModel):
    id: str
    url: str
    material_status: str
    material_sha256: str | None = Field(pattern=SHA256)
    observations: list[str]


class Registry(StrictModel):
    schema_version: Literal["unspun-r1-input-registry-v1"]
    status: Literal["registered_not_frozen"]
    registered_on: str
    base_revision: str
    reference_date: str
    expected_candidate_count: StrictInt
    expected_source_count: StrictInt
    expected_observation_count: StrictInt
    expected_legacy_events: StrictInt
    expected_legacy_articles: StrictInt
    files: list[PinnedFile]
    candidates: list[CandidatePin]
    boundaries: dict[str, list[str]]


class Review(StrictModel):
    worth_reading_now: Literal["yes", "no", "unknown"] | None = None
    importance_1_to_5: StrictInt | None = Field(default=None, ge=1, le=5)
    interest_1_to_5: StrictInt | None = Field(default=None, ge=1, le=5)
    place: Literal["selection", "recommended", "latest", "exclude", "defer"] | None = None
    reason: str | None = Field(default=None, max_length=4000)
    interest: Literal["yes", "no"] | None = None

    def has_input(self) -> bool:
        return any(value is not None and value != "" for value in self.model_dump().values())


class FeedbackCandidate(StrictModel):
    id: str
    title: str
    url: str
    publication: dict[str, Any]
    material_status: str
    material_sha256: str | None = Field(pattern=SHA256)
    human_review: Review


class Feedback(StrictModel):
    schema_version: Literal["unspun-r0-reading-feedback-v1"]
    dataset_sha256: str = Field(pattern=SHA256)
    contents: dict[str, Review]
    topics: dict[str, Review]
    experience: dict[str, str | int | float]
    updated_at: str | None
    exported_at: str
    reference_date: str
    layout_schema: Literal["unspun-r0-reading-layout-v1"]
    selection_version: str
    ranking_method: Literal["manual_layout_for_review_not_algorithm_evaluation"]
    reviewed_content_count: StrictInt = Field(ge=0)
    candidates: list[FeedbackCandidate]

    @field_validator("updated_at", "exported_at")
    @classmethod
    def aware_timestamp(cls, value: str | None) -> str | None:
        if value is not None and datetime.fromisoformat(value).utcoffset() is None:
            raise ValueError("feedback timestamps must include a timezone")
        return value


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path.name}")
    return cast("dict[str, Any]", value)


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _unique(items: list[dict[str, Any]], key: str, label: str) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for item in items:
        identity = str(item[key])
        if identity in indexed:
            raise ValueError(f"duplicate {label}: {identity}")
        indexed[identity] = item
    return indexed


def _pinned_documents(root: Path, registry: Registry) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    seen_paths: set[Path] = set()
    for entry in registry.files:
        path = (root / entry.path).resolve()
        if Path(entry.path).is_absolute() or not path.is_relative_to(root.resolve()):
            raise ValueError("pinned paths must stay inside the repository")
        if entry.role in paths or path in seen_paths:
            raise ValueError("pinned file roles and paths must be unique")
        if file_hash(path) != entry.sha256:
            raise ValueError(f"input fingerprint changed: {entry.path}")
        paths[entry.role] = path
        seen_paths.add(path)
    return paths


def validate_feedback(
    path: Path, candidates_path: Path, candidates: dict[str, dict[str, Any]], layout: dict[str, Any]
) -> dict[str, Any]:
    """Validate both copies of exported reviews; file metadata does not prove authorship."""
    feedback = Feedback.model_validate(read_object(path))
    if feedback.dataset_sha256 != file_hash(candidates_path):
        raise ValueError("feedback belongs to a different candidate file")
    if feedback.reference_date != layout["reference_date"]:
        raise ValueError("feedback reference date changed")
    if feedback.selection_version not in layout["selection_versions"]:
        raise ValueError("unknown feedback selection version")
    topic_ids = {topic["id"] for topic in layout["topics"]}
    if set(feedback.contents) - candidates.keys() or set(feedback.topics) - topic_ids:
        raise ValueError("feedback contains unknown content or topic targets")
    if set(feedback.experience) - EXPERIENCE_FIELDS:
        raise ValueError("feedback contains unknown experience fields")
    exported = _unique([item.model_dump() for item in feedback.candidates], "id", "feedback ID")
    if exported.keys() != candidates.keys():
        raise ValueError("feedback must retain every candidate exactly once")
    metadata_fields = ("title", "url", "publication", "material_status", "material_sha256")
    for identity, candidate in candidates.items():
        item = exported[identity]
        if any(item[field] != candidate[field] for field in metadata_fields):
            raise ValueError(f"feedback candidate provenance changed: {identity}")
        expected = feedback.contents.get(identity, Review()).model_dump()
        if item["human_review"] != expected:
            raise ValueError(f"conflicting feedback copies: {identity}")
    reviews = {
        identity: review.model_dump()
        for identity, review in feedback.contents.items()
        if review.has_input()
    }
    if feedback.reviewed_content_count != len(reviews):
        raise ValueError("feedback reviewed count does not match actual inputs")
    return {
        "status": "validated_export",
        "sha256": file_hash(path),
        "reviewer_kind": "declared_user_export",
        "identity_verified": False,
        "content_count_with_any_input": len(reviews),
        "reviews": reviews,
        "topics": {
            identity: review.model_dump()
            for identity, review in feedback.topics.items()
            if review.has_input()
        },
        "experience": feedback.experience,
        "updated_at": feedback.updated_at,
        "exported_at": feedback.exported_at,
        "quality_passed": None,
    }


def inspect_registry(
    root: Path, registry_path: Path, feedback_path: Path | None = None
) -> dict[str, Any]:
    registry = Registry.model_validate(read_object(registry_path))
    paths = _pinned_documents(root, registry)
    required = {
        "r0_candidates",
        "r0_observations",
        "r0_layout",
        "legacy_raw_snapshot",
        "legacy_technical_snapshot",
        "legacy_user_labels",
        "legacy_technical_labels",
    }
    if not required <= paths.keys():
        raise ValueError("required evidence roles are missing")
    document = read_object(paths["r0_candidates"])
    if document["schema_version"] != "unspun-r0-review-candidates-v1":
        raise ValueError("unsupported candidate schema")
    if document["reference_date"] != registry.reference_date:
        raise ValueError("candidate reference date changed")
    candidates = _unique(document["candidates"], "id", "candidate ID")
    pins = _unique([pin.model_dump() for pin in registry.candidates], "id", "candidate pin")
    if len(candidates) != registry.expected_candidate_count or candidates.keys() != pins.keys():
        raise ValueError("candidate membership changed")
    observations = _unique(
        read_object(paths["r0_observations"])["observations"], "observation_id", "observation ID"
    )
    if len(observations) != registry.expected_observation_count:
        raise ValueError("observation count changed")
    for identity, candidate in candidates.items():
        if any(candidate[field] != pins[identity][field] for field in pins[identity]):
            raise ValueError(f"candidate identity or material pin changed: {identity}")
        if set(candidate["observations"]) - observations.keys():
            raise ValueError(f"candidate observation reference is missing: {identity}")
        if any(candidate["human_review"][field] is not None for field in REVIEW_FIELDS):
            raise ValueError("R0 inputs must retain empty user labels; import feedback separately")
        fingerprint = candidate["material_sha256"]
        if fingerprint is not None and not re.fullmatch(SHA256, fingerprint):
            raise ValueError(f"invalid material fingerprint: {identity}")
    sources = {candidate["requested_source"] for candidate in candidates.values()}
    if len(sources) != registry.expected_source_count:
        raise ValueError("source count changed")
    for identities in registry.boundaries.values():
        if not identities or set(identities) - candidates.keys():
            raise ValueError("boundary cases must reference registered candidates")

    raw_events = _unique(read_object(paths["legacy_raw_snapshot"])["events"], "id", "raw event")
    events = _unique(
        read_object(paths["legacy_technical_snapshot"])["events"], "id", "technical event"
    )
    article_ids = {article["id"] for event in events.values() for article in event["articles"]}
    raw_articles = {article["id"] for event in raw_events.values() for article in event["articles"]}
    labels = _unique(read_object(paths["legacy_user_labels"])["labels"], "event_id", "user label")
    technical = _unique(
        read_object(paths["legacy_technical_labels"])["labels"], "event_id", "technical label"
    )
    if not (events.keys() == raw_events.keys() == labels.keys() == technical.keys()):
        raise ValueError("legacy event membership changed")
    if len(events) != registry.expected_legacy_events:
        raise ValueError("legacy event count changed")
    if raw_articles != article_ids or len(article_ids) != registry.expected_legacy_articles:
        raise ValueError("legacy article membership changed")
    for identity, label in labels.items():
        if any(
            label[field] != technical[identity][field]
            for field in ("importance_band", "worth_reading")
        ):
            raise ValueError(f"legacy subjective labels changed: {identity}")

    feedback: dict[str, Any] = (
        validate_feedback(
            feedback_path, paths["r0_candidates"], candidates, read_object(paths["r0_layout"])
        )
        if feedback_path
        else {"status": "not_provided", "reviews": {}, "quality_passed": None}
    )
    return {
        "schema_version": "unspun-r1-registration-report-v1",
        "registry_sha256": file_hash(registry_path),
        "registration_valid": True,
        "technical_status": "technical_not_ready",
        "technical_ready": False,
        "technical_blockers": [
            "R1-00B technical expectations, holdout inputs and baseline outputs are not frozen",
            "Source observation windows and tolerances are not fixed per path",
            "Material fingerprints register identity; "
            "body availability and content were not checked",
        ],
        "user_quality_status": "user_quality_pending_final_acceptance",
        "user_quality_passed": None,
        "candidate_count": len(candidates),
        "source_count_with_samples": len(sources),
        "observation_count": len(observations),
        "reference_date": registry.reference_date,
        "material_status_counts": dict(
            sorted(
                Counter(candidate["material_status"] for candidate in candidates.values()).items()
            )
        ),
        "material_fingerprint_count": sum(
            candidate["material_sha256"] is not None for candidate in candidates.values()
        ),
        "missing_material_fingerprints": [
            identity
            for identity, candidate in candidates.items()
            if candidate["material_sha256"] is None
        ],
        "body_availability_checked": False,
        "legacy": {
            "event_count": len(events),
            "article_count": len(article_ids),
            "subjective_labels_equal": True,
            "subjective_origin": "legacy_user_labels; preserved without reinterpretation",
            "technical_origin": "legacy_technical_labels; AI technical review is separate",
            "worth_reading_true": sum(label["worth_reading"] is True for label in labels.values()),
            "worth_reading_false": sum(
                label["worth_reading"] is False for label in labels.values()
            ),
            "ranking_regression_executed": False,
        },
        "feedback": feedback,
        "boundaries": registry.boundaries,
        "pinned_file_count": len(paths),
        "network_database_or_model_calls": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--feedback", type=Path)
    parser.add_argument("--output", required=True, type=Path, help="Must be a new report file")
    parser.add_argument("--require-technical-ready", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = inspect_registry(args.root, args.registry, args.feedback)
    except (OSError, ValueError, TypeError, KeyError) as error:
        report = {
            "schema_version": "unspun-r1-registration-report-v1",
            "registration_valid": False,
            "technical_ready": False,
            "technical_status": "technical_not_ready",
            "user_quality_passed": None,
            "errors": [str(error)],
        }
    output = cast("Path", args.output)
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    except OSError as error:
        parser.error(f"cannot create report (existing evidence is never overwritten): {error}")
    print(
        f"registration_valid={report['registration_valid']} "
        f"technical_ready={report['technical_ready']} user_quality=pending_final_acceptance"
    )
    if not report["registration_valid"]:
        return 2
    return 1 if args.require_technical_ready else 0


if __name__ == "__main__":
    raise SystemExit(main())
