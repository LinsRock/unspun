"""Offline M3-B ranking candidates; deliberately not used by the live API."""

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, Field, PositiveInt

from unspun.core.grounding import quote_in_source
from unspun.core.publication import publication_bounds

BEIJING = ZoneInfo("Asia/Shanghai")
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
PERIODS = ("today", "24h", "7d", "all")
SORTS = ("newest", "hot", "important", "activity", "baseline")


class ArticleSample(BaseModel):
    id: PositiveInt
    source_id: str = Field(min_length=1)
    title: str
    url: str
    published_at: AwareDatetime | None
    fetched_at: AwareDatetime
    # None preserves the legacy candidate; explicit unknown forbids RSS fallback.
    reported_at: AwareDatetime | None = None
    reported_date: date | None = None
    reported_precision: Literal["time", "date", "unknown"] | None = None
    reported_basis: str | None = None
    impact_original_excerpt: str | None = Field(default=None, max_length=2500)


class PublicImpactEvidence(BaseModel):
    article_id: PositiveInt
    quote: str = Field(min_length=1)


class EventSample(BaseModel):
    id: PositiveInt
    title: str | None
    score_final: Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)] | None
    first_seen_at: AwareDatetime
    changed_at: AwareDatetime
    articles: list[ArticleSample]
    # Evidence must match bounded original excerpts attached to member articles.
    public_impact_status: Literal["supported", "routine", "unknown"] = "unknown"
    public_impact_urgent: bool = False
    public_impact_evidence: list[PublicImpactEvidence] = Field(
        default_factory=list[PublicImpactEvidence]
    )
    public_impact_assessed_at: AwareDatetime | None = None


@dataclass(frozen=True)
class CandidateParams:
    half_life_hours: float = 24
    growth_hours: float = 6
    growth_bonus: float = 0.5
    future_tolerance_minutes: float = 5
    public_impact_hours: float = 48

    def __post_init__(self) -> None:
        values = (
            self.half_life_hours,
            self.growth_hours,
            self.growth_bonus,
            self.future_tolerance_minutes,
            self.public_impact_hours,
        )
        if not all(math.isfinite(v) for v in values):
            raise ValueError("candidate parameters must be finite")
        if self.half_life_hours <= 0 or self.growth_hours <= 0 or self.public_impact_hours <= 0:
            raise ValueError("candidate windows must be positive")
        if self.growth_bonus < 0 or self.future_tolerance_minutes < 0:
            raise ValueError("candidate bonus and tolerance must not be negative")


DEFAULT_PARAMS = CandidateParams()


@dataclass(frozen=True)
class ReportTimes:
    earliest: datetime | None
    latest: datetime | None
    valid_count: int
    missing_count: int
    invalid_count: int
    earliest_lower: datetime | None = None
    earliest_upper: datetime | None = None
    latest_lower: datetime | None = None
    latest_upper: datetime | None = None
    earliest_date: date | None = None
    latest_date: date | None = None
    earliest_precision: str = "unknown"
    latest_precision: str = "unknown"


@dataclass(frozen=True)
class RankedEvent:
    id: int
    earliest: datetime | None
    latest: datetime | None
    metric: float | None
    active_publishers: int
    valid_count: int
    missing_count: int
    invalid_count: int
    earliest_lower: datetime | None = None
    earliest_upper: datetime | None = None
    latest_lower: datetime | None = None
    latest_upper: datetime | None = None
    earliest_date: date | None = None
    latest_date: date | None = None
    earliest_precision: str = "unknown"
    latest_precision: str = "unknown"
    public_impact_boosted: bool = False


def _utc(as_of: datetime) -> datetime:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("snapshot time must include a timezone")
    return as_of.astimezone(UTC)


def valid_publication(article: ArticleSample, as_of: datetime, params: CandidateParams) -> bool:
    return _bounds(article, as_of, params) is not None


def _bounds(
    article: ArticleSample, as_of: datetime, params: CandidateParams
) -> tuple[datetime, datetime] | None:
    if article.fetched_at > as_of or article.reported_precision == "unknown":
        return None
    if article.reported_precision is not None:
        return publication_bounds(
            article.reported_at if article.reported_precision == "time" else None,
            article.reported_date if article.reported_precision == "date" else None,
            article.fetched_at,
            as_of,
        )
    publication = article.published_at
    valid = (
        article.fetched_at <= as_of
        and publication is not None
        and EPOCH <= publication <= as_of
        and publication <= article.fetched_at + timedelta(minutes=params.future_tolerance_minutes)
    )
    return (
        (publication.astimezone(UTC), publication.astimezone(UTC))
        if valid and publication
        else None
    )


def report_times(
    event: EventSample, as_of: datetime, params: CandidateParams = DEFAULT_PARAMS
) -> ReportTimes:
    as_of = _utc(as_of)
    visible = [a for a in event.articles if a.fetched_at <= as_of]
    times = [(bounds, a) for a in visible if (bounds := _bounds(a, as_of, params)) is not None]
    missing = sum(
        a.reported_precision == "unknown"
        or (a.reported_precision == "time" and a.reported_at is None)
        or (a.reported_precision == "date" and a.reported_date is None)
        or (a.reported_precision is None and a.published_at is None)
        for a in visible
    )
    earliest = min(times, key=lambda item: (item[0][0], item[1].id)) if times else None
    latest = max(times, key=lambda item: (item[0][0], item[1].id)) if times else None
    return ReportTimes(
        earliest[0][0] if earliest and earliest[1].reported_precision != "date" else None,
        latest[0][0] if latest and latest[1].reported_precision != "date" else None,
        len(times),
        missing,
        len(visible) - len(times) - missing,
        earliest[0][0] if earliest else None,
        earliest[0][1] if earliest else None,
        latest[0][0] if latest else None,
        latest[0][1] if latest else None,
        earliest[1].reported_date if earliest else None,
        latest[1].reported_date if latest else None,
        (earliest[1].reported_precision or "time") if earliest else "unknown",
        (latest[1].reported_precision or "time") if latest else "unknown",
    )


def window_start(period: str, as_of: datetime) -> datetime | None:
    as_of = _utc(as_of)
    if period == "today":
        local = as_of.astimezone(BEIJING)
        return datetime.combine(local.date(), time.min, tzinfo=BEIJING).astimezone(UTC)
    if period in {"24h", "7d"}:
        return as_of - timedelta(hours=24 if period == "24h" else 168)
    if period == "all":
        return None
    raise ValueError("invalid feed range")


def rank_events(
    events: list[EventSample],
    sort: str,
    period: str,
    as_of: datetime,
    publisher_groups: dict[str, str] | None = None,
    params: CandidateParams = DEFAULT_PARAMS,
    baseline_half_life_hours: float = 24,
    article_publisher_groups: dict[int, str] | None = None,
) -> list[RankedEvent]:
    """Compare candidates without changing stored scores, membership or timestamps.

    Missing media mappings fall back to configuration source IDs in draft
    reports only. The suite's readiness gate requires human-reviewed groups.
    """
    if not math.isfinite(baseline_half_life_hours) or baseline_half_life_hours <= 0:
        raise ValueError("baseline half-life must be positive and finite")
    if sort not in SORTS:
        raise ValueError("invalid feed sort")
    as_of = _utc(as_of)
    start = window_start(period, as_of)
    if sort in {"hot", "activity"} and start is None:
        start = as_of - timedelta(hours=24)
    groups = publisher_groups or {}
    article_groups = article_publisher_groups or {}
    rows: list[RankedEvent] = []
    discovered: dict[int, datetime] = {}
    for event in events:
        if event.first_seen_at > as_of:
            continue
        times = report_times(event, as_of, params)
        discovered[event.id] = event.first_seen_at
        metric: float | None = None
        active_publishers = 0
        if sort == "baseline":
            if event.score_final is not None:
                age = (as_of - event.changed_at).total_seconds() / 3600
                metric = event.score_final * 2 ** (-age / baseline_half_life_hours)
        elif times.earliest_lower is None:
            if period != "all":
                continue
        elif sort in {"newest", "important"}:
            if start is not None and times.earliest_lower < start:
                continue
            metric = times.earliest_lower.timestamp() if sort == "newest" else event.score_final
        else:
            assert start is not None
            first_per_group: dict[str, datetime] = {}
            for article in event.articles:
                bounds = _bounds(article, as_of, params)
                if bounds is not None:
                    published = bounds[0]
                    group = article_groups.get(
                        article.id, groups.get(article.source_id, article.source_id)
                    )
                    first_per_group[group] = min(published, first_per_group.get(group, published))
            # Group before applying the window: later reposts cannot revive a publisher.
            first_per_group = {
                group: t for group, t in first_per_group.items() if start <= t <= as_of
            }
            if not first_per_group:
                continue
            active_publishers = len(first_per_group)
            activity = sum(
                2 ** (-((as_of - t).total_seconds() / 3600) / params.half_life_hours)
                for t in first_per_group.values()
            )
            growth = sum(
                t >= as_of - timedelta(hours=params.growth_hours) for t in first_per_group.values()
            )
            metric = activity + (params.growth_bonus * growth if sort == "hot" else 0)
        rows.append(
            RankedEvent(
                event.id,
                times.earliest,
                times.latest,
                metric,
                active_publishers,
                times.valid_count,
                times.missing_count,
                times.invalid_count,
                times.earliest_lower,
                times.earliest_upper,
                times.latest_lower,
                times.latest_upper,
                times.earliest_date,
                times.latest_date,
                times.earliest_precision,
                times.latest_precision,
                sort == "important" and _public_impact_boost(event, times, as_of, params),
            )
        )

    def ordering(row: RankedEvent) -> tuple[bool, bool, float, float, int]:
        if sort == "baseline":
            event = next(e for e in events if e.id == row.id)
            return (
                False,
                row.metric is not None,
                row.metric or 0,
                event.changed_at.timestamp(),
                row.id,
            )
        if row.earliest_lower is None:
            return False, False, discovered[row.id].timestamp(), 0, row.id
        tie_time = row.latest_lower if sort in {"hot", "activity"} else row.earliest_lower
        assert tie_time is not None
        return (
            row.public_impact_boosted,
            True,
            row.metric if row.metric is not None else -1,
            tie_time.timestamp(),
            row.id,
        )

    return sorted(rows, key=ordering, reverse=True)


def _public_impact_boost(
    event: EventSample, times: ReportTimes, as_of: datetime, params: CandidateParams
) -> bool:
    """Use approved evidence and original source bounds, never titles or changed_at."""
    members = {article.id: article for article in event.articles if article.fetched_at <= as_of}
    return (
        event.public_impact_status == "supported"
        and event.public_impact_urgent
        and bool(event.public_impact_evidence)
        and all(
            e.article_id in members
            and quote_in_source(e.quote, members[e.article_id].impact_original_excerpt or "")
            for e in event.public_impact_evidence
        )
        and (event.public_impact_assessed_at is None or event.public_impact_assessed_at <= as_of)
        and times.earliest_lower is not None
        and as_of - timedelta(hours=params.public_impact_hours) <= times.earliest_lower <= as_of
    )
