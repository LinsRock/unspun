from datetime import UTC, datetime, timedelta

import pytest

NOW = datetime(2026, 10, 14, 0, 30, tzinfo=UTC)


def event_sample(
    event_id: int,
    published: list[tuple[str, datetime | None]],
    *,
    score: float | None = 50,
    changed_at: datetime = NOW,
    fetched_at: datetime = NOW,
) -> dict[str, object]:
    return {
        "id": event_id,
        "title": f"event-{event_id}",
        "score_final": score,
        "first_seen_at": NOW - timedelta(days=400),
        "changed_at": changed_at,
        "articles": [
            {
                "id": event_id * 100 + i,
                "source_id": source,
                "title": "article",
                "url": f"https://example.com/{event_id}/{i}",
                "published_at": time,
                "fetched_at": fetched_at,
            }
            for i, (source, time) in enumerate(published)
        ],
    }


def rank(samples: list[dict[str, object]], sort: str = "newest", period: str = "all"):
    from unspun.evaluation.feed_ranking import EventSample, rank_events

    return rank_events([EventSample.model_validate(s) for s in samples], sort, period, NOW)


def test_late_fetched_old_news_does_not_lead_newest() -> None:
    old = event_sample(1, [("old", datetime(2025, 8, 20, tzinfo=UTC))], score=99)
    fresh = event_sample(2, [("fresh", NOW - timedelta(hours=1))], score=10)
    assert [r.id for r in rank([old, fresh])] == [2, 1]
    assert [r.id for r in rank([old, fresh], "hot", "24h")] == [2]


def test_later_reprint_cannot_move_earliest_time_forward() -> None:
    old = event_sample(1, [("a", NOW - timedelta(days=5)), ("b", NOW)])
    fresh = event_sample(2, [("c", NOW - timedelta(hours=2))])
    assert [r.id for r in rank([old, fresh])] == [2, 1]
    assert rank([old])[0].earliest == NOW - timedelta(days=5)
    earlier = event_sample(1, [("a", NOW - timedelta(days=5)), ("b", NOW - timedelta(days=9))])
    assert rank([earlier])[0].earliest == NOW - timedelta(days=9)


def test_missing_future_and_ancient_anomalies_are_unknown() -> None:
    missing = event_sample(1, [("a", None)])
    future = event_sample(2, [("b", NOW + timedelta(minutes=6))])
    epoch = event_sample(3, [("c", datetime(1960, 1, 1, tzinfo=UTC))])
    fresh = event_sample(4, [("d", NOW)])
    rows = rank([missing, future, epoch, fresh])
    assert [r.id for r in rows] == [4, 3, 2, 1]
    assert rows[1].invalid_count == 1
    assert rows[2].invalid_count == 1
    assert rows[3].missing_count == 1
    assert [r.id for r in rank([missing, future, epoch, fresh], period="7d")] == [4]


def test_publication_tolerance_is_relative_to_fetch_not_query_time() -> None:
    fetch = NOW - timedelta(hours=1)
    valid = event_sample(1, [("a", fetch + timedelta(minutes=5))], fetched_at=fetch)
    invalid = event_sample(2, [("b", fetch + timedelta(minutes=5, seconds=1))], fetched_at=fetch)
    rows = rank([valid, invalid])
    assert rows[0].earliest == fetch + timedelta(minutes=5)
    assert rows[1].earliest is None
    assert rows[1].invalid_count == 1


def test_fixed_as_of_excludes_later_fetch_and_future_events() -> None:
    later_fetch = event_sample(
        1, [("a", NOW - timedelta(hours=2))], fetched_at=NOW + timedelta(seconds=1)
    )
    later_event = event_sample(2, [("a", NOW)])
    later_event["first_seen_at"] = NOW + timedelta(seconds=1)
    assert rank([later_event]) == []
    assert rank([later_fetch])[0].valid_count == 0
    assert rank([later_fetch])[0].missing_count == 0


def test_today_differs_from_rolling_24h_in_beijing() -> None:
    from unspun.evaluation.feed_ranking import window_start

    yesterday_beijing = NOW - timedelta(hours=9)
    sample = event_sample(1, [("a", yesterday_beijing)])
    assert window_start("today", NOW) == datetime(2026, 10, 13, 16, tzinfo=UTC)
    assert rank([sample], period="today") == []
    assert len(rank([sample], period="24h")) == 1
    exact = event_sample(2, [("a", NOW)])
    assert len(rank([exact], period="today")) == 1


def test_same_media_repeats_and_sections_do_not_increase_heat() -> None:
    from unspun.evaluation.feed_ranking import EventSample, rank_events

    first = NOW - timedelta(hours=3)
    base = event_sample(1, [("bbc-world", first)])
    repeated = event_sample(2, [("bbc-world", first), ("bbc-world", NOW), ("bbc-tech", NOW)])
    mapping = {"bbc-world": "bbc", "bbc-tech": "bbc"}
    rows = rank_events(
        [EventSample.model_validate(s) for s in [base, repeated]], "hot", "24h", NOW, mapping
    )
    assert rows[0].metric == pytest.approx(rows[1].metric)
    assert rows[0].active_publishers == 1
    assert rows[0].metric == pytest.approx(2 ** (-3 / 24) + 0.5)


def test_growth_reward_and_no_growth_comparator_are_separate() -> None:
    sample = event_sample(1, [("a", NOW - timedelta(hours=2)), ("b", NOW - timedelta(hours=7))])
    heat = rank([sample], "hot", "24h")[0]
    activity = rank([sample], "activity", "24h")[0]
    assert activity.metric is not None
    assert heat.metric == pytest.approx(activity.metric + 0.5)
    assert heat.active_publishers == 2


def test_hot_all_uses_24h_while_7d_uses_selected_window() -> None:
    sample = event_sample(1, [("a", NOW - timedelta(days=2))])
    assert rank([sample], "hot", "all") == []
    assert len(rank([sample], "hot", "7d")) == 1


def test_important_reuses_existing_score_and_old_baseline_uses_changed_at() -> None:
    high = event_sample(
        1, [("a", NOW - timedelta(days=2))], score=90, changed_at=NOW - timedelta(days=3)
    )
    low = event_sample(2, [("b", NOW)], score=60)
    unscored = event_sample(3, [("c", NOW)], score=None)
    assert [r.id for r in rank([high, low, unscored], "important")] == [1, 2, 3]
    assert [r.id for r in rank([high, low, unscored], "baseline")] == [2, 1, 3]
    assert rank([high], "baseline")[0].metric == pytest.approx(11.25)


def test_unknown_group_and_same_score_ties_are_deterministic() -> None:
    a = event_sample(1, [("a", NOW)], score=60)
    b = event_sample(2, [("b", NOW)], score=60)
    unknown = event_sample(3, [("c", None)], score=100)
    assert [r.id for r in rank([a, unknown, b], "important")] == [2, 1, 3]
    assert [r.id for r in rank([a, b])] == [2, 1]


@pytest.mark.parametrize("sort,period", [("changed", "all"), ("newest", "yesterday")])
def test_invalid_sort_or_range_is_rejected(sort: str, period: str) -> None:
    with pytest.raises(ValueError):
        rank([], sort, period)


def test_naive_snapshot_times_are_rejected() -> None:
    from pydantic import ValidationError

    from unspun.evaluation.feed_ranking import EventSample

    sample = event_sample(1, [("a", NOW)])
    sample["changed_at"] = datetime(2026, 10, 14)
    with pytest.raises(ValidationError):
        EventSample.model_validate(sample)


def test_candidate_half_life_does_not_change_historical_baseline() -> None:
    from unspun.evaluation.feed_ranking import CandidateParams, EventSample, rank_events

    old = EventSample.model_validate(
        event_sample(1, [("a", NOW)], score=90, changed_at=NOW - timedelta(hours=24))
    )
    fresh = EventSample.model_validate(event_sample(2, [("b", NOW)], score=60))
    rows = rank_events(
        [old, fresh], "baseline", "all", NOW, params=CandidateParams(half_life_hours=48)
    )
    assert [r.id for r in rows] == [2, 1]
    assert rows[1].metric == pytest.approx(45)


def test_aggregator_entries_can_have_different_article_publishers() -> None:
    from unspun.evaluation.feed_ranking import EventSample, rank_events

    sample = EventSample.model_validate(event_sample(1, [("hn-front", NOW), ("hn-front", NOW)]))
    rows = rank_events(
        [sample],
        "hot",
        "24h",
        NOW,
        article_publisher_groups={100: "publisher-a", 101: "publisher-b"},
    )
    assert rows[0].active_publishers == 2
    assert rows[0].metric == pytest.approx(3)


def test_direct_and_aggregated_links_to_same_publisher_count_once() -> None:
    from unspun.evaluation.feed_ranking import EventSample, rank_events

    sample = EventSample.model_validate(event_sample(1, [("arxiv-ai", NOW), ("hn-front", NOW)]))
    rows = rank_events(
        [sample],
        "hot",
        "24h",
        NOW,
        {"arxiv-ai": "arxiv", "hn-front": "hn"},
        article_publisher_groups={101: "arxiv"},
    )
    assert rows[0].active_publishers == 1
    assert rows[0].metric == pytest.approx(1.5)


def reviewed(sample: dict[str, object], precision: str, value: object = None) -> dict[str, object]:
    from typing import cast

    articles = cast(list[dict[str, object]], sample["articles"])
    for article in articles:
        article["reported_precision"] = precision
        article["reported_basis"] = "primary-page"
        article["reported_at" if precision == "time" else "reported_date"] = value
    return sample


def urgent(sample: dict[str, object]) -> dict[str, object]:
    from typing import cast

    articles = cast(list[dict[str, object]], sample["articles"])
    articles[0]["impact_original_excerpt"] = "Ongoing harm requires immediate public action."
    sample.update(
        public_impact_status="supported",
        public_impact_urgent=True,
        public_impact_evidence=[{"article_id": articles[0]["id"], "quote": "Ongoing harm"}],
    )
    return sample


def test_reviewed_unknown_never_falls_back_to_feed_update() -> None:
    sample = reviewed(event_sample(1, [("a", NOW)]), "unknown")
    assert rank([sample], period="24h") == []
    assert rank([sample])[0].earliest is None
    assert rank([sample])[0].missing_count == 1
    assert rank([sample], "hot", "24h") == []


def test_date_only_preserves_display_and_uses_conservative_bounds() -> None:
    from datetime import date

    sample = reviewed(event_sample(1, [("a", NOW)]), "date", date(2026, 10, 13))
    row = rank([sample])[0]
    assert row.earliest is None
    assert row.earliest_date == date(2026, 10, 13)
    assert row.earliest_precision == "date"
    assert row.earliest_lower == datetime(2026, 10, 12, 10, tzinfo=UTC)
    assert row.earliest_upper == NOW
    assert row.valid_count == 1
    assert rank([sample], period="24h") == []
    assert rank([sample], "important", "24h") == []
    assert rank([sample], "hot", "24h") == []


def test_original_time_and_same_publisher_repost_do_not_revive_heat() -> None:
    old = NOW - timedelta(days=5)
    sample = reviewed(event_sample(1, [("a", NOW)]), "time", old)
    assert rank([sample])[0].earliest == old
    assert rank([sample], "hot", "24h") == []
    legacy_repost = event_sample(2, [("a", old), ("a", NOW)])
    assert rank([legacy_repost], "hot", "24h") == []


def test_fresh_supported_public_harm_precedes_high_score_product_only_in_important() -> None:
    harm = urgent(event_sample(1, [("a", NOW - timedelta(hours=2))], score=10))
    product = event_sample(2, [("b", NOW)], score=90)
    assert [r.id for r in rank([product, harm], "important")] == [1, 2]
    assert rank([harm], "important")[0].public_impact_boosted
    assert [r.id for r in rank([product, harm])] == [2, 1]
    assert [r.id for r in rank([product, harm], "hot")] == [2, 1]


@pytest.mark.parametrize(
    "publication", [NOW - timedelta(hours=48, seconds=1), NOW + timedelta(seconds=1), None]
)
def test_old_future_or_unknown_harm_is_not_boosted(publication: datetime | None) -> None:
    harm = urgent(event_sample(1, [("a", publication)], score=10))
    product = event_sample(2, [("b", NOW)], score=90)
    assert [r.id for r in rank([harm, product], "important")] == [2, 1]
    assert not rank([harm], "important")[0].public_impact_boosted


def test_public_impact_requires_supported_member_evidence_and_nonfuture_assessment() -> None:
    cases: list[dict[str, object]] = [
        {"public_impact_status": "unknown"},
        {"public_impact_evidence": []},
        {"public_impact_evidence": [{"article_id": 9999, "quote": "Harm"}]},
        {"public_impact_assessed_at": NOW + timedelta(seconds=1)},
    ]
    for changes in cases:
        sample = urgent(event_sample(1, [("a", NOW)], score=10))
        sample.update(changes)
        assert not rank([sample], "important")[0].public_impact_boosted


def test_uncertain_old_date_is_not_boosted_even_when_feed_is_fresh() -> None:
    from datetime import date

    sample = urgent(reviewed(event_sample(1, [("a", NOW)]), "date", date(2026, 10, 12)))
    assert not rank([sample], "important")[0].public_impact_boosted


@pytest.mark.parametrize("hours", [0, -1, float("nan"), float("inf")])
def test_public_impact_window_must_be_positive_finite(hours: float) -> None:
    from unspun.evaluation.feed_ranking import CandidateParams

    with pytest.raises(ValueError):
        CandidateParams(public_impact_hours=hours)


def test_date_bounds_order_events_without_fabricating_instants() -> None:
    from datetime import date

    dated = reviewed(event_sample(1, [("a", NOW)], score=90), "date", date(2026, 10, 13))
    precise = event_sample(2, [("b", NOW - timedelta(hours=25))], score=10)
    assert [r.id for r in rank([dated, precise])] == [2, 1]
    assert rank([dated], period="7d")[0].earliest_date == date(2026, 10, 13)
    assert rank([dated], "hot", "7d")[0].metric == pytest.approx(2 ** (-38.5 / 24))


def test_public_impact_uses_earliest_source_and_includes_exact_48h_boundary() -> None:
    boundary = urgent(event_sample(1, [("a", NOW - timedelta(hours=48))], score=10))
    assert rank([boundary], "important")[0].public_impact_boosted
    old = urgent(event_sample(2, [("a", NOW - timedelta(days=5)), ("b", NOW)], score=10))
    assert not rank([old], "important")[0].public_impact_boosted


def test_public_impact_parameters_are_immutable() -> None:
    from dataclasses import FrozenInstanceError

    from unspun.evaluation.feed_ranking import CandidateParams

    params = CandidateParams()
    assert params.public_impact_hours == 48
    with pytest.raises(FrozenInstanceError):
        params.public_impact_hours = 24  # pyright: ignore[reportAttributeAccessIssue]


@pytest.mark.parametrize("excerpt", [None, "", "Routine product announcement."])
def test_public_impact_quote_must_match_member_original_excerpt(excerpt: str | None) -> None:
    from typing import cast

    sample = urgent(event_sample(1, [("a", NOW)], score=10))
    articles = cast(list[dict[str, object]], sample["articles"])
    articles[0]["impact_original_excerpt"] = excerpt
    assert not rank([sample], "important")[0].public_impact_boosted


def test_public_impact_original_excerpt_is_bounded() -> None:
    from typing import cast

    from pydantic import ValidationError

    from unspun.evaluation.feed_ranking import EventSample

    sample = urgent(event_sample(1, [("a", NOW)]))
    articles = cast(list[dict[str, object]], sample["articles"])
    articles[0]["impact_original_excerpt"] = "x" * 2501
    with pytest.raises(ValidationError):
        EventSample.model_validate(sample)
