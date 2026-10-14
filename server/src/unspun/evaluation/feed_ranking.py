"""Offline M3-B ranking candidates; deliberately not used by the live API."""

import math
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, Field, PositiveInt

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


class EventSample(BaseModel):
    id: PositiveInt
    title: str | None
    score_final: Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)] | None
    first_seen_at: AwareDatetime
    changed_at: AwareDatetime
    articles: list[ArticleSample]


@dataclass(frozen=True)
class CandidateParams:
    half_life_hours: float = 24
    growth_hours: float = 6
    growth_bonus: float = 0.5
    future_tolerance_minutes: float = 5

    def __post_init__(self) -> None:
        values = (
            self.half_life_hours,
            self.growth_hours,
            self.growth_bonus,
            self.future_tolerance_minutes,
        )
        if not all(math.isfinite(v) for v in values):
            raise ValueError("candidate parameters must be finite")
        if self.half_life_hours <= 0 or self.growth_hours <= 0:
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


def _utc(as_of: datetime) -> datetime:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("snapshot time must include a timezone")
    return as_of.astimezone(UTC)


def valid_publication(article: ArticleSample, as_of: datetime, params: CandidateParams) -> bool:
    publication = article.published_at
    return (
        article.fetched_at <= as_of
        and publication is not None
        and EPOCH <= publication <= as_of
        and publication <= article.fetched_at + timedelta(minutes=params.future_tolerance_minutes)
    )


def report_times(
    event: EventSample, as_of: datetime, params: CandidateParams = DEFAULT_PARAMS
) -> ReportTimes:
    as_of = _utc(as_of)
    visible = [a for a in event.articles if a.fetched_at <= as_of]
    times = [
        a.published_at.astimezone(UTC)
        for a in visible
        if a.published_at is not None and valid_publication(a, as_of, params)
    ]
    missing = sum(a.published_at is None for a in visible)
    return ReportTimes(
        min(times) if times else None,
        max(times) if times else None,
        len(times),
        missing,
        len(visible) - len(times) - missing,
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
        elif times.earliest is None:
            if period != "all":
                continue
        elif sort in {"newest", "important"}:
            if start is not None and times.earliest < start:
                continue
            metric = times.earliest.timestamp() if sort == "newest" else event.score_final
        else:
            assert start is not None
            first_per_group: dict[str, datetime] = {}
            for article in event.articles:
                published = article.published_at
                if (
                    published is not None
                    and valid_publication(article, as_of, params)
                    and start <= published <= as_of
                ):
                    group = groups.get(article.source_id, article.source_id)
                    first_per_group[group] = min(published, first_per_group.get(group, published))
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
            )
        )

    def ordering(row: RankedEvent) -> tuple[bool, float, float, int]:
        if sort == "baseline":
            event = next(e for e in events if e.id == row.id)
            return row.metric is not None, row.metric or 0, event.changed_at.timestamp(), row.id
        if row.earliest is None:
            return False, discovered[row.id].timestamp(), 0, row.id
        tie_time = row.latest if sort in {"hot", "activity"} else row.earliest
        assert tie_time is not None
        return True, row.metric if row.metric is not None else -1, tie_time.timestamp(), row.id

    return sorted(rows, key=ordering, reverse=True)
