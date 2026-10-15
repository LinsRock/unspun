import json
from datetime import UTC, date, datetime, timedelta

import pytest

from unspun.core import publication

FETCHED = datetime(2026, 10, 14, 12, tzinfo=UTC)
URL = "https://example.com/story"


def meta(value: str, name: str = "article:published_time") -> str:
    return f'<meta property="{name}" content="{value}">'


def ld(value: object) -> str:
    return f'<script type="application/ld+json">{json.dumps(value)}</script>'


@pytest.mark.parametrize("value", ["2026-10-13T18:30:00+08:00", "2026-10-13T10:30:00Z"])
def test_explicit_timezone(value: str) -> None:
    result = publication.extract_publication(meta(value), URL, FETCHED)
    assert result.reported_at == datetime(2026, 10, 13, 10, 30, tzinfo=UTC)
    assert result.reported_date == date(2026, 10, 13)
    assert result.precision == "time"
    assert result.basis == "meta:article:published_time"
    assert result.status == "ok"


@pytest.mark.parametrize("value", ["2026-10-13", "2026-10-13T18:30:00"])
def test_no_timezone_preserves_only_date(value: str) -> None:
    result = publication.extract_publication(meta(value, "datePublished"), URL, FETCHED)
    assert result.reported_at is None
    assert result.reported_date == date(2026, 10, 13)
    assert result.precision == "date"


@pytest.mark.parametrize("kind", ["Article", "NewsArticle", "BlogPosting", "ScholarlyArticle"])
def test_matching_jsonld(kind: str) -> None:
    result = publication.extract_publication(
        ld({"@type": kind, "url": URL, "datePublished": "2026-10-13T10:30:00Z"}), URL, FETCHED
    )
    assert result.precision == "time"
    assert result.basis == "jsonld:datePublished"


def test_canonical_tracking_and_graph_identity() -> None:
    canonical = "https://example.com/new-story"
    html = f'<link rel="canonical" href="{canonical}">' + ld(
        {
            "@graph": [
                {
                    "@type": "NewsArticle",
                    "@id": canonical + "#article",
                    "datePublished": "2026-10-13",
                }
            ]
        }
    )
    assert publication.extract_publication(html, URL, FETCHED).precision == "date"
    html = ld({"@type": "Article", "url": URL + "?utm_source=feed", "datePublished": "2026-10-13"})
    assert publication.extract_publication(html, URL, FETCHED).precision == "date"


@pytest.mark.parametrize("article_url", ["https://example.com/footer", URL + "?id=other", None])
def test_other_or_unidentified_articles_ignored(article_url: str | None) -> None:
    html = ld({"@type": "Article", "url": article_url, "datePublished": "2026-10-13"})
    assert publication.extract_publication(html, URL, FETCHED).precision == "unknown"


def test_modified_only_unknown() -> None:
    html = meta("2026-10-13", "article:modified_time") + ld(
        {"@type": "Article", "url": URL, "dateModified": "2026-10-14"}
    )
    assert publication.extract_publication(html, URL, FETCHED).precision == "unknown"


def test_conflict() -> None:
    result = publication.extract_publication(
        meta("2026-10-13T10:00:00Z") + meta("2026-10-12T10:00:00Z"), URL, FETCHED
    )
    assert result.precision == "unknown"
    assert result.status == "conflict"


def test_compatible_date_and_timestamp() -> None:
    html = meta("2026-10-13") + ld(
        {"@type": "Article", "url": URL, "datePublished": "2026-10-13T10:00:00Z"}
    )
    assert publication.extract_publication(html, URL, FETCHED).precision == "time"


@pytest.mark.parametrize(
    "value", ["2026-10-14T12:05:01Z", "1969-12-31T23:59:59Z", "2026-10-16", "not a date"]
)
def test_invalid_future_unknown(value: str) -> None:
    assert publication.extract_publication(meta(value), URL, FETCHED).precision == "unknown"


def test_malformed_and_deep_json_does_not_hide_meta() -> None:
    for body in ("{broken", "[" * 2000 + "0" + "]" * 2000):
        html = '<script type="application/ld+json">' + body + "</script>" + meta("2026-10-13")
        assert publication.extract_publication(html, URL, FETCHED).reported_date == date(
            2026, 10, 13
        )


def test_oversize_html_rejected() -> None:
    html = "x" * (2 * 1024 * 1024 + 1) + meta("2026-10-13")
    assert publication.extract_publication(html, URL, FETCHED).precision == "unknown"


def test_arxiv_v1_original() -> None:
    html = (
        '<div class="submission-history">Submission history<br>'
        "[v1] Tue, 13 Oct 2026 10:30:00 UTC (123 KB)<br>"
        "[v2] Wed, 14 Oct 2026 11:30:00 UTC (124 KB)</div>"
    )
    result = publication.extract_publication(html, "https://arxiv.org/abs/2610.12345v2", FETCHED)
    assert result.reported_at == datetime(2026, 10, 13, 10, 30, tzinfo=UTC)
    assert result.basis == "arxiv:submission-history:v1"


@pytest.mark.parametrize(
    "content",
    [
        "[v2] Wed, 14 Oct 2026 11:30:00 UTC",
        "[v1] Tue, 13 Oct 2026 10:30:00 UTC [v1] Mon, 12 Oct 2026 10:30:00 UTC",
    ],
)
def test_arxiv_missing_ambiguous_v1(content: str) -> None:
    html = '<div class="submission-history">' + content + "</div>"
    result = publication.extract_publication(html, "https://arxiv.org/abs/2610.12345", FETCHED)
    assert result.precision == "unknown"


def test_exact_bounds_cutoffs() -> None:
    instant = FETCHED - timedelta(hours=1)
    assert publication.publication_bounds(instant, instant.date(), FETCHED, FETCHED) == (
        instant,
        instant,
    )
    assert (
        publication.publication_bounds(
            FETCHED + timedelta(minutes=6), None, FETCHED, FETCHED + timedelta(days=1)
        )
        is None
    )
    assert (
        publication.publication_bounds(instant, None, FETCHED, instant - timedelta(seconds=1))
        is None
    )
    assert (
        publication.publication_bounds(datetime(1969, 1, 1, tzinfo=UTC), None, FETCHED, FETCHED)
        is None
    )
    assert publication.publication_bounds(datetime(2026, 10, 13), None, FETCHED, FETCHED) is None


def test_date_bounds_timezone_extremes() -> None:
    assert publication.publication_bounds(None, date(2026, 10, 12), FETCHED, FETCHED) == (
        datetime(2026, 10, 11, 10, tzinfo=UTC),
        datetime(2026, 10, 13, 12, tzinfo=UTC),
    )


def test_date_bounds_capped_empty_rejected() -> None:
    assert publication.publication_bounds(
        None, date(2026, 10, 14), FETCHED, FETCHED + timedelta(days=1)
    ) == (datetime(2026, 10, 13, 10, tzinfo=UTC), FETCHED + timedelta(minutes=5))
    assert publication.publication_bounds(
        None, date(2026, 10, 14), FETCHED, FETCHED - timedelta(hours=2)
    ) == (datetime(2026, 10, 13, 10, tzinfo=UTC), FETCHED - timedelta(hours=2))
    assert publication.publication_bounds(None, date(2026, 10, 16), FETCHED, FETCHED) is None
    assert publication.publication_bounds(None, date(1969, 1, 1), FETCHED, FETCHED) is None
    assert publication.publication_bounds(None, None, FETCHED, FETCHED) is None


def test_invalid_original_metadata_does_not_allow_cherry_picking() -> None:
    html = meta("2026-10-13") + meta("2026-10-20T10:00:00Z")
    result = publication.extract_publication(html, URL, FETCHED)
    assert result.precision == "unknown"
    assert result.status == "invalid"


def test_contradictory_article_identities_are_ignored() -> None:
    html = ld(
        {
            "@type": "Article",
            "url": "https://example.com/footer",
            "mainEntityOfPage": {"@id": URL},
            "datePublished": "2026-10-13",
        }
    )
    assert publication.extract_publication(html, URL, FETCHED).precision == "unknown"


def test_arxiv_update_metadata_is_not_original_without_v1() -> None:
    html = meta("2026-10-13")
    result = publication.extract_publication(html, "https://arxiv.org/abs/2610.12345v2", FETCHED)
    assert result.precision == "unknown"


def test_unrelated_host_cannot_use_arxiv_history() -> None:
    html = '<div class="submission-history">[v1] Tue, 13 Oct 2026 10:30:00 UTC</div>'
    assert publication.extract_publication(html, URL, FETCHED).precision == "unknown"


def test_five_minute_tolerance_is_inclusive() -> None:
    result = publication.extract_publication(meta("2026-10-14T12:05:00Z"), URL, FETCHED)
    assert result.reported_at == FETCHED + timedelta(minutes=5)


def test_datetime_extremes_and_naive_observation_fail_closed() -> None:
    assert publication.publication_bounds(None, date.max, FETCHED, FETCHED) is None
    assert (
        publication.extract_publication(
            meta("2026-10-13"), URL, FETCHED.replace(tzinfo=None)
        ).precision
        == "unknown"
    )


def test_nontracking_query_order_is_preserved_for_identity() -> None:
    html = ld({"@type": "Article", "url": URL + "?tag=b&tag=a", "datePublished": "2026-10-13"})
    requested = URL + "?tag=a&tag=b"
    assert publication.extract_publication(html, requested, FETCHED).precision == "unknown"


@pytest.mark.parametrize("suffix", ["+08:00", "-05:00", "garbage"])
def test_arxiv_utc_requires_complete_timezone_token(suffix: str) -> None:
    html = '<div class="submission-history">[v1] Tue, 13 Oct 2026 10:30:00 UTC' + suffix + "</div>"
    result = publication.extract_publication(html, "https://arxiv.org/abs/2610.12345", FETCHED)
    assert result.precision == "unknown"


def test_conflicting_canonicals_fail_closed() -> None:
    html = (
        '<link rel="canonical" href="https://example.com/one">'
        '<link rel="canonical" href="https://example.com/two">'
        + ld({"@type": "Article", "url": URL, "datePublished": "2026-10-13"})
    )
    result = publication.extract_publication(html, URL, FETCHED)
    assert result.precision == "unknown"
    assert result.status == "conflict"


def test_duplicate_jsonld_publication_values_are_not_last_wins() -> None:
    html = (
        '<script type="application/ld+json">'
        '{"@type":"Article","url":"https://example.com/story",'
        '"datePublished":"2026-10-12","datePublished":"2026-10-13"}</script>'
    )
    result = publication.extract_publication(html, URL, FETCHED)
    assert result.precision == "unknown"
    assert result.status == "conflict"


def test_epoch_date_uncertainty_lower_bound_is_capped() -> None:
    assert publication.publication_bounds(None, date(1970, 1, 1), FETCHED, FETCHED) == (
        datetime(1970, 1, 1, tzinfo=UTC),
        datetime(1970, 1, 2, 12, tzinfo=UTC),
    )


def test_duplicate_publication_values_cannot_bypass_json_node_budget() -> None:
    repeated = ',"datePublished":"2026-10-13"' * 10_001
    html = (
        '<script type="application/ld+json">'
        '{"@type":"Article","url":"https://example.com/story"' + repeated + "}</script>"
    )
    assert publication.extract_publication(html, URL, FETCHED).precision == "unknown"


def test_json_object_budget_is_shared_across_graph_articles() -> None:
    repeated = ',"datePublished":"2026-10-13"' * 5_001
    article = '{"@type":"Article","url":"https://example.com/story"' + repeated + "}"
    html = (
        '<script type="application/ld+json">{"@graph":[' + article + "," + article + "]}</script>"
    )
    assert publication.extract_publication(html, URL, FETCHED).precision == "unknown"
