"""Review provenance, readiness and reproducible offline ranking reports."""

import hashlib
import json
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    PositiveInt,
    StrictBool,
    StringConstraints,
    ValidationError,
)

from unspun.core import public_impact, publication
from unspun.evaluation import feed_ranking
from unspun.evaluation.feed_ranking import (
    DEFAULT_PARAMS,
    PERIODS,
    SORTS,
    CandidateParams,
    EventSample,
    rank_events,
    valid_publication,
)

Nonempty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ReviewerKind = Literal["human", "ai-technical"]


class Snapshot(BaseModel):
    provenance: Literal["production-read-only-snapshot"]
    captured_at: AwareDatetime
    event_count: PositiveInt
    baseline_half_life_hours: Annotated[float, Field(gt=0, allow_inf_nan=False)] = 24
    events: list[EventSample]


class Reprint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    article_id: PositiveInt
    original_url: Nonempty


class EventLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: PositiveInt
    reviewer_kind: ReviewerKind = "human"
    subjective_labels_origin: Nonempty | None = None
    domain: Nonempty | None = None
    importance_band: Annotated[int, Field(strict=True, ge=1, le=5)] | None = None
    worth_reading: StrictBool | None = None
    timestamp_review: dict[str, Literal["valid", "missing", "anomalous"]] = Field(
        default_factory=dict
    )
    publisher_groups: dict[str, Nonempty] = Field(default_factory=dict)
    article_publisher_groups: dict[str, Nonempty] = Field(default_factory=dict)
    reprints_reviewed: StrictBool = False
    known_reprints: list[Reprint] = Field(default_factory=lambda: list[Reprint]())
    reviewed_by: Nonempty | None = None
    reviewed_at: AwareDatetime | None = None


class ExpectedPair(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reviewer_kind: ReviewerKind = "human"
    sort: Literal["newest", "hot", "important"]
    range: Literal["today", "24h", "7d", "all"]
    before_event_id: PositiveInt
    after_event_id: PositiveInt
    reason: Nonempty
    reviewed_by: Nonempty
    reviewed_at: AwareDatetime


class Annotations(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Nonempty
    reviewer_kind: ReviewerKind = "human"
    technical_review_origin: Nonempty | None = None
    snapshot_sha256: str
    frozen: StrictBool = False
    frozen_sha256: str | None = None
    parameters_sha256: str | None = None
    candidate_source_sha256: str | None = None
    reviewed_by: Nonempty | None = None
    reviewed_at: AwareDatetime | None = None
    coverage_reviewed: StrictBool = False
    coverage_notes: Nonempty | None = None
    labels: list[EventLabel]
    expected_pairs: list[ExpectedPair]


def _json_default(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"unsupported JSON type: {type(value).__name__}")


def content_hash(document: Any) -> str:
    canonical = json.dumps(
        document, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=_json_default
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def candidate_source_hash() -> str:
    files = [
        Path(__file__),
        Path(feed_ranking.__file__),
        Path(publication.__file__),
        Path(public_impact.__file__),
    ]
    return hashlib.sha256(b"\n".join(path.read_bytes() for path in files)).hexdigest()


def _readiness(
    snapshot: Snapshot,
    annotations: Annotations,
    snapshot_hash: str,
    params: CandidateParams,
) -> tuple[list[str], dict[str, str], dict[int, str]]:
    issues: list[str] = []
    groups: dict[str, str] = {}
    article_groups: dict[int, str] = {}
    if not 30 <= len(snapshot.events) <= 50:
        issues.append("standard set must contain 30 to 50 real events")
    if snapshot.event_count < len(snapshot.events):
        issues.append("snapshot count is smaller than its sampled events")
    if annotations.snapshot_sha256 != snapshot_hash:
        issues.append("snapshot hash does not match reviewed input")
    if annotations.parameters_sha256 != content_hash(asdict(params)):
        issues.append("candidate parameter hash does not match reviewed parameters")
    if annotations.candidate_source_sha256 != candidate_source_hash():
        issues.append("candidate source hash does not match reviewed code")
    if not annotations.frozen:
        issues.append("annotations are not frozen")
    role = "human" if annotations.reviewer_kind == "human" else "AI technical"
    if annotations.reviewer_kind == "ai-technical" and annotations.technical_review_origin is None:
        issues.append("AI technical suite requires explicit technical review origin")
    if annotations.reviewed_by is None or annotations.reviewed_at is None:
        issues.append(f"suite requires a {role} reviewer and timezone-aware review time")
    if not annotations.coverage_reviewed or annotations.coverage_notes is None:
        issues.append(f"domain and case coverage requires explicit {role} review")
    if len({label.domain for label in annotations.labels if label.domain}) < 3:
        issues.append(f"standard set must cover at least three {role}-labelled domains")
    events = {event.id: event for event in snapshot.events}
    if len(events) != len(snapshot.events):
        issues.append("duplicate event IDs in snapshot")
    articles = [a for event in snapshot.events for a in event.articles]
    if len({a.id for a in articles}) != len(articles):
        issues.append("duplicate article IDs in snapshot")
    if any(not a.url.startswith(("http://", "https://")) for a in articles):
        issues.append("source links must use http(s)")
    labels = {label.event_id: label for label in annotations.labels}
    if len(labels) != len(annotations.labels):
        issues.append("duplicate event labels")
    if set(labels) != set(events):
        issues.append("labels must match all sampled event IDs exactly")
    for event_id, event in events.items():
        label = labels.get(event_id)
        if label is None:
            continue
        prefix = f"event {event_id}: "
        if event.public_impact_urgent or event.public_impact_status == "supported":
            impact = public_impact.parse_impact(
                {
                    "reason": "Frozen source-grounded public-impact assessment",
                    "is_urgent": event.public_impact_urgent,
                    "evidence": [item.model_dump() for item in event.public_impact_evidence],
                },
                [
                    public_impact.ImpactArticle(
                        id=article.id,
                        title=article.title,
                        text=article.impact_original_excerpt or "",
                        reported_at=article.reported_at,
                        reported_date=article.reported_date,
                    )
                    for article in event.articles
                ],
            )
            if impact.status == "unknown":
                issues.append(
                    prefix + "public-impact evidence not verified against original excerpt"
                )
        label_role = "human" if label.reviewer_kind == "human" else "AI technical"
        if label.reviewer_kind == "ai-technical" and label.subjective_labels_origin is None:
            issues.append(
                prefix + "AI technical labels require original user subjective labels origin"
            )
        if label.reviewer_kind == "ai-technical" and annotations.technical_review_origin is None:
            issues.append(prefix + "AI technical review requires suite technical review origin")
        for field in ("domain", "importance_band", "worth_reading", "reviewed_by", "reviewed_at"):
            if getattr(label, field) is None:
                issues.append(prefix + f"missing {label_role} {field}")
        if not event.articles:
            issues.append(prefix + "no source articles to review")
        if not label.reprints_reviewed:
            issues.append(prefix + "reprint relations have not been reviewed")
        article_ids = {str(a.id) for a in event.articles}
        if set(label.timestamp_review) != article_ids:
            issues.append(prefix + "timestamp review must cover every member article")
        for article in event.articles:
            expected = (
                "missing"
                if article.reported_precision == "unknown"
                or (article.reported_precision is None and article.published_at is None)
                else "valid"
                if valid_publication(article, snapshot.captured_at, params)
                else "anomalous"
            )
            actual = label.timestamp_review.get(str(article.id))
            if actual is not None and actual != expected:
                issues.append(prefix + f"timestamp classification differs for article {article.id}")
            if article.fetched_at > snapshot.captured_at:
                issues.append(prefix + f"article {article.id} was fetched after snapshot")
        source_ids = {a.source_id for a in event.articles}
        if set(label.publisher_groups) - source_ids:
            issues.append(prefix + "publisher groups reference non-member sources")
        if set(label.article_publisher_groups) - article_ids:
            issues.append(prefix + "article publisher groups reference non-member articles")
        for article in event.articles:
            article_group = label.article_publisher_groups.get(str(article.id))
            if article_group is not None:
                article_groups[article.id] = article_group
            elif article.source_id not in label.publisher_groups:
                issues.append(prefix + f"missing publisher group for article {article.id}")
        for source, group in label.publisher_groups.items():
            if source in groups and groups[source] != group:
                issues.append(prefix + f"conflicting publisher group for {source}")
            groups[source] = group
        if any(str(reprint.article_id) not in article_ids for reprint in label.known_reprints):
            issues.append(prefix + "reprint article is outside the reviewed event")
        if any(
            not r.original_url.startswith(("http://", "https://")) for r in label.known_reprints
        ):
            issues.append(prefix + "reprint origin must use http(s)")
    if {pair.sort for pair in annotations.expected_pairs} != {"newest", "hot", "important"}:
        issues.append(f"{role} priority pairs must cover newest, hot and important")
    for pair in annotations.expected_pairs:
        if pair.reviewer_kind == "ai-technical" and annotations.technical_review_origin is None:
            issues.append("AI technical priority pair requires suite technical review origin")
        if pair.before_event_id == pair.after_event_id:
            issues.append("priority pair must compare two different events")
        if pair.before_event_id not in events or pair.after_event_id not in events:
            issues.append("priority pair refers to an event outside the snapshot")
    return issues, groups, article_groups


def evaluate_suite(
    snapshot_document: dict[str, Any],
    annotations_document: dict[str, Any],
    params: CandidateParams = DEFAULT_PARAMS,
) -> dict[str, Any]:
    """Drafts can be ranked, but cannot satisfy the reviewed acceptance gate."""
    snapshot_hash = content_hash(snapshot_document)
    report: dict[str, Any] = {
        "version": "m3b-ranking-report-v1",
        "ready": False,
        "passed": False,
        "live_model_calls": False,
        "production_data_modified": False,
        "readiness_issues": [],
        "pair_results": [],
        "rankings": {},
        "parameters": asdict(params),
        "hashes": {
            "snapshot": snapshot_hash,
            "annotations": content_hash(annotations_document),
            "parameters": content_hash(asdict(params)),
            "source": candidate_source_hash(),
        },
        "limitations": [
            "Reviewer metadata and origin are recorded assertions, not identity verifications.",
            "Media activity is not independent factual evidence; unknown reprints remain unknown.",
            "Priority pairs assess only declared preferences, not overall ranking accuracy.",
        ],
    }
    try:
        snapshot = Snapshot.model_validate(snapshot_document)
        annotations = Annotations.model_validate(annotations_document)
    except ValidationError as error:
        report["readiness_issues"] = [
            f"invalid input at {'.'.join(map(str, e['loc']))}: {e['msg']}"
            for e in error.errors(include_input=False, include_url=False)
        ]
        return report
    issues, groups, article_groups = _readiness(snapshot, annotations, snapshot_hash, params)
    frozen_hash = content_hash(
        {k: v for k, v in annotations_document.items() if k != "frozen_sha256"}
    )
    if annotations.frozen and annotations.frozen_sha256 != frozen_hash:
        issues.append("frozen annotation hash does not match reviewed labels and priority pairs")
    report["readiness_issues"] = issues
    report["ready"] = not issues
    report["captured_at"] = snapshot.captured_at.isoformat()
    report["baseline_half_life_hours"] = snapshot.baseline_half_life_hours
    report["event_count"] = len(snapshot.events)
    report["reviewer_kind"] = annotations.reviewer_kind
    report["technical_review_origin"] = annotations.technical_review_origin
    grouping_roles = {label.reviewer_kind for label in annotations.labels}
    grouping_review = next(iter(grouping_roles)) if len(grouping_roles) == 1 else "mixed"
    report["publisher_grouping"] = (
        f"{grouping_review}-reviewed" if not issues else "draft-unverified"
    )
    positions: dict[tuple[str, str], dict[int, int]] = {}
    for period in PERIODS:
        report["rankings"][period] = {}
        for sort in SORTS:
            # The old API had no range filter. Every baseline repeats its
            # original full-universe ordering rather than inventing one.
            rows = rank_events(
                snapshot.events,
                sort,
                "all" if sort == "baseline" else period,
                snapshot.captured_at,
                groups,
                params,
                baseline_half_life_hours=snapshot.baseline_half_life_hours,
                article_publisher_groups=article_groups,
            )
            report["rankings"][period][sort] = [
                json.loads(json.dumps(asdict(row), default=_json_default)) for row in rows
            ]
            positions[sort, period] = {row.id: i for i, row in enumerate(rows)}
    for pair in annotations.expected_pairs:
        order = positions[pair.sort, pair.range]
        before = order.get(pair.before_event_id)
        after = order.get(pair.after_event_id)
        passed = before is not None and after is not None and before < after
        report["pair_results"].append(
            {
                **pair.model_dump(mode="json"),
                "before_position": before,
                "after_position": after,
                "passed": passed,
                "reason": (
                    "event outside candidate window"
                    if before is None or after is None
                    else pair.reason
                ),
            }
        )
    report["passed"] = report["ready"] and all(p["passed"] for p in report["pair_results"])
    return report
