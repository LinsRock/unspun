from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from unspun.api.admin.content import (
    count_articles,
    count_events,
    list_articles,
    list_events,
    read_article,
    read_event,
)
from unspun.core.models import Article, Event, EventViewpoint


def test_article_time_basis_and_missing_report_time(db_session: Session) -> None:
    now = datetime.now(UTC)
    event = Event(title="Time basis", first_seen_at=now)
    db_session.add(event)
    db_session.flush()
    article = Article(
        source_id="time-basis",
        url=f"https://example.com/time-{event.id}",
        title="Time basis",
        published_at=None,
        fetched_at=now,
        event_id=event.id,
    )
    db_session.add(article)
    db_session.flush()
    start, end = now - timedelta(minutes=1), now + timedelta(seconds=1)
    fetched = list_articles(db_session, start, end, time_basis="fetched_at")
    reported = list_articles(db_session, start, end, time_basis="published_at")
    assert article.id in {row["id"] for row in fetched}
    assert article.id not in {row["id"] for row in reported}


def test_article_keyword_escapes_sql_wildcards(db_session: Session) -> None:
    now = datetime.now(UTC)
    db_session.add_all(
        [
            Article(
                source_id="search",
                url=f"https://example.com/percent-{now.timestamp()}",
                title="A%literal",
                fetched_at=now,
            ),
            Article(
                source_id="search",
                url=f"https://example.com/other-{now.timestamp()}",
                title="A-literal",
                fetched_at=now,
            ),
        ]
    )
    db_session.flush()
    rows = list_articles(
        db_session, now - timedelta(minutes=1), now + timedelta(seconds=1), keyword="%"
    )
    assert [row["title"] for row in rows] == ["A%literal"]


def test_article_equal_timestamps_use_id_tiebreaker(db_session: Session) -> None:
    now = datetime.now(UTC)
    source_id = f"stable-{now.timestamp()}"
    db_session.add_all(
        [
            Article(
                source_id=source_id,
                url=f"https://example.com/stable-a-{now.timestamp()}",
                title="First",
                fetched_at=now,
            ),
            Article(
                source_id=source_id,
                url=f"https://example.com/stable-b-{now.timestamp()}",
                title="Second",
                fetched_at=now,
            ),
        ]
    )
    db_session.flush()
    rows = list_articles(
        db_session,
        now - timedelta(minutes=1),
        now + timedelta(seconds=1),
        source_id=source_id,
    )
    assert [row["title"] for row in rows] == ["Second", "First"]
    page_one = list_articles(
        db_session,
        now - timedelta(minutes=1),
        now + timedelta(seconds=1),
        source_id=source_id,
        limit=1,
        offset=0,
    )
    page_two = list_articles(
        db_session,
        now - timedelta(minutes=1),
        now + timedelta(seconds=1),
        source_id=source_id,
        limit=1,
        offset=1,
    )
    assert [r["title"] for r in page_one] == ["Second"]
    assert [r["title"] for r in page_two] == ["First"]
    assert (
        count_articles(
            db_session, now - timedelta(minutes=1), now + timedelta(seconds=1), source_id=source_id
        )
        == 2
    )


def test_event_report_times_and_foreign_viewpoint_claims(db_session: Session) -> None:
    now = datetime.now(UTC)
    event = Event(title="Event", first_seen_at=now)
    db_session.add(event)
    db_session.flush()
    own = Article(
        source_id="one",
        url=f"https://example.com/own-{event.id}",
        title="Own",
        published_at=now - timedelta(days=1),
        fetched_at=now,
        event_id=event.id,
    )
    foreign = Article(
        source_id="two",
        url=f"https://example.com/foreign-{event.id}",
        title="Foreign",
        fetched_at=now,
    )
    db_session.add_all([own, foreign])
    db_session.flush()
    db_session.add(
        EventViewpoint(
            event_id=event.id,
            payload={
                "claims": [
                    {"article_id": own.id, "claim": "valid"},
                    {"article_id": foreign.id, "claim": "invalid"},
                ],
                "disagreements": [],
            },
            input_fingerprint="test",
            model="test",
        )
    )
    db_session.flush()
    rows = list_events(db_session, now - timedelta(days=2), now + timedelta(seconds=1))
    row = next(row for row in rows if row["id"] == event.id)
    assert row["earliest_published_at"] == own.published_at
    assert row["latest_published_at"] == own.published_at
    assert row["article_count"] == 1
    assert row["source_count"] == 1
    detail = read_event(db_session, event.id)
    assert detail is not None
    assert [claim["article_id"] for claim in detail["viewpoint"]["payload"]["claims"]] == [own.id]


def test_missing_report_time_requires_explicit_mode(db_session: Session) -> None:
    now = datetime.now(UTC)
    event = Event(title="Undated", first_seen_at=now)
    db_session.add(event)
    db_session.flush()
    db_session.add(
        Article(
            source_id="missing-report-time",
            url=f"https://example.com/undated-{event.id}",
            title="Undated",
            fetched_at=now,
            event_id=event.id,
        )
    )
    db_session.flush()
    start, end = now - timedelta(minutes=1), now + timedelta(seconds=1)
    assert event.id not in {r["id"] for r in list_events(db_session, start, end)}
    missing = list_events(db_session, start, end, time_status="missing", limit=1)
    assert missing[0]["id"] == event.id
    assert missing[0]["range_time_basis"] == "first_seen_at"
    assert missing[0]["earliest_published_at"] is None
    assert count_events(db_session, start, end, time_status="missing") >= 1


def test_event_report_range_and_database_page_are_stable(db_session: Session) -> None:
    now = datetime.now(UTC)
    source_id = f"event-page-{now.timestamp()}"
    ids: list[int] = []
    for index in range(2):
        event = Event(title=f"Page {index}", first_seen_at=now)
        db_session.add(event)
        db_session.flush()
        ids.append(event.id)
        db_session.add(
            Article(
                source_id=source_id,
                url=f"https://example.com/{source_id}-{index}",
                title=f"Page {index}",
                fetched_at=now,
                published_at=now - timedelta(days=3),
                event_id=event.id,
            )
        )
    db_session.flush()
    recent_start, recent_end = now - timedelta(minutes=1), now + timedelta(seconds=1)
    assert not {r["id"] for r in list_events(db_session, recent_start, recent_end)}.intersection(
        ids
    )
    older_start = now - timedelta(days=4)
    older_end = now - timedelta(days=2)
    assert count_events(db_session, older_start, older_end, source_id=source_id) == 2
    first = list_events(db_session, older_start, older_end, source_id=source_id, limit=1)
    second = list_events(db_session, older_start, older_end, source_id=source_id, limit=1, offset=1)
    assert [r["id"] for r in first + second] == list(reversed(ids))


def test_article_status_filter_matches_database_count(db_session: Session) -> None:
    now = datetime.now(UTC)
    source_id = f"status-{now.timestamp()}"
    db_session.add_all(
        [
            Article(
                source_id=source_id,
                url=f"https://example.com/{source_id}-done",
                title="Done",
                fetched_at=now,
                summary_zh="Summary",
            ),
            Article(
                source_id=source_id,
                url=f"https://example.com/{source_id}-pending",
                title="Pending",
                fetched_at=now,
            ),
        ]
    )
    db_session.flush()
    start, end = now - timedelta(minutes=1), now + timedelta(seconds=1)
    assert (
        count_articles(db_session, start, end, source_id=source_id, processing_status="summarized")
        == 1
    )
    rows = list_articles(
        db_session,
        start,
        end,
        source_id=source_id,
        processing_status="summarized",
        limit=1,
    )
    assert [r["title"] for r in rows] == ["Done"]


def test_article_detail_reports_existing_processing_and_quality(db_session: Session) -> None:
    now = datetime.now(UTC)
    article = Article(
        source_id="detail",
        url=f"https://example.com/detail-{now.timestamp()}",
        title="Detail",
        fetched_at=now,
        summary_zh="Summary",
        summary_grounding={"status": "grounded"},
    )
    db_session.add(article)
    db_session.flush()
    detail = read_article(db_session, article.id)
    assert detail is not None
    assert detail["processing_status"] == "summarized"
    assert detail["quality_status"] == "grounded"
