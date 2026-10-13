from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from unspun.api.admin.sources import list_sources, source_summary
from unspun.core.models import Article, FetchLog


def test_removed_source_and_zero_update_fetch(db_session: Session) -> None:
    now = datetime.now(UTC)
    removed = f"removed-{now.timestamp()}"
    db_session.add(FetchLog(source_id=removed, status="ok", new_articles=0, run_at=now))
    db_session.flush()

    result = list_sources(db_session, now - timedelta(days=1), now + timedelta(seconds=1))
    item = next(item for item in result if item["id"] == removed)
    assert item["configured"] is False
    assert item["name"] is None
    assert item["health"] == "ok"
    assert item["successful_fetches"] == 1
    assert item["new_articles"] == 0
    assert item["success_rate"] == 1.0


def test_latest_error_uses_run_time_then_id(db_session: Session) -> None:
    now = datetime.now(UTC)
    source = f"error-{now.timestamp()}"
    db_session.add_all(
        [
            FetchLog(source_id=source, status="error", error="z-old", run_at=now),
            FetchLog(source_id=source, status="error", error="a-new", run_at=now),
        ]
    )
    db_session.flush()
    result = list_sources(db_session, now - timedelta(days=1), now + timedelta(seconds=1))
    item = next(item for item in result if item["id"] == source)
    assert item["last_error"] == "a-new"
    assert item["health"] == "error"


def test_article_only_source_has_unknown_success_rate(db_session: Session) -> None:
    now = datetime.now(UTC)
    source = f"article-{now.timestamp()}"
    db_session.add(
        Article(
            source_id=source, url=f"https://example.com/{source}", title="Article", fetched_at=now
        )
    )
    db_session.flush()
    result = list_sources(db_session, now - timedelta(days=1), now + timedelta(seconds=1))
    item = next(item for item in result if item["id"] == source)
    assert item["success_rate"] is None
    assert item["health"] == "no_runs"
    assert item["article_count"] == 1


def test_source_sort_has_stable_id_tiebreaker(db_session: Session) -> None:
    from unspun.api.admin.sources import filter_sources

    now = datetime.now(UTC)
    ids = [f"tie-b-{now.timestamp()}", f"tie-a-{now.timestamp()}"]
    for source_id in ids:
        db_session.add(FetchLog(source_id=source_id, status="ok", new_articles=0, run_at=now))
    db_session.flush()
    rows = list_sources(db_session, now - timedelta(days=1), now + timedelta(seconds=1))
    sorted_rows = filter_sources([r for r in rows if r["id"] in ids], sort="articles")
    assert [r["id"] for r in sorted_rows] == sorted(ids)


def test_source_summary_counts_zero_update_success_as_successful(db_session: Session) -> None:
    now = datetime.now(UTC)
    source = f"summary-{now.timestamp()}"
    db_session.add(FetchLog(source_id=source, status="ok", new_articles=0, run_at=now))
    db_session.flush()
    rows = list_sources(db_session, now - timedelta(days=1), now + timedelta(seconds=1))
    summary = source_summary(rows)
    assert summary["successful_sources"] >= 1
    assert summary["productive_sources"] == sum(bool(r["new_articles"]) for r in rows)


def test_health_and_latest_error_are_all_time_while_counts_are_period_only(
    db_session: Session,
) -> None:
    now = datetime.now(UTC)
    source_id = f"all-time-{now.timestamp()}"
    db_session.add_all(
        [
            FetchLog(
                source_id=source_id, status="ok", new_articles=0, run_at=now - timedelta(days=2)
            ),
            FetchLog(source_id=source_id, status="error", error="last error", run_at=now),
        ]
    )
    db_session.flush()
    rows = list_sources(db_session, now - timedelta(days=1), now - timedelta(hours=1))
    item = next(row for row in rows if row["id"] == source_id)
    assert item["health"] == "error"
    assert item["last_error"] == "last error"
    assert item["last_success_at"] == now - timedelta(days=2)
    assert item["successful_fetches"] == 0
    assert item["failed_fetches"] == 0
    assert item["success_rate"] is None
    assert item["period_latest_status"] is None
