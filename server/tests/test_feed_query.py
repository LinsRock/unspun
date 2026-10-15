from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from unspun.core.feed_query import feed_page
from unspun.core.models import Article, Event


def test_database_filters_before_limit_and_original_time(db_session: Session) -> None:
    now = datetime.now(UTC)
    events = [
        Event(title=f"story-{i}", score_final=100 - i, first_seen_at=now - timedelta(minutes=1))
        for i in range(65)
    ]
    db_session.add_all(events)
    db_session.flush()
    for i, event in enumerate(events):
        db_session.add(
            Article(
                source_id="test",
                url=f"https://feed-test/{i}",
                title="body",
                event=event,
                reported_at=now - timedelta(hours=65 - i),
                reported_precision="time",
                fetched_at=now - timedelta(minutes=1),
                publisher_group="publisher",
            )
        )
    db_session.flush()
    page = feed_page(db_session, "newest", "24h", 2, now, None)
    assert [row["id"] for row in page.rows] == [events[-1].id, events[-2].id]
    next_page = feed_page(db_session, "newest", "24h", 2, now, page.next_cursor)
    assert [row["id"] for row in next_page.rows] == [events[-3].id, events[-4].id]


def test_hot_groups_before_window_and_unknown_only_all(db_session: Session) -> None:
    now = datetime.now(UTC)
    old = Event(title="reposted", first_seen_at=now - timedelta(minutes=1))
    unknown = Event(title="unknown", first_seen_at=now - timedelta(minutes=1))
    db_session.add_all([old, unknown])
    db_session.flush()
    for index, hours in enumerate([72, 1]):
        db_session.add(
            Article(
                source_id="test",
                url=f"https://repost-test/{index}",
                title="x",
                event=old,
                reported_at=now - timedelta(hours=hours),
                reported_precision="time",
                fetched_at=now - timedelta(minutes=1),
                publisher_group="same",
            )
        )
    db_session.flush()
    assert not feed_page(db_session, "hot", "24h", 100, now, None).rows
    rows = feed_page(db_session, "hot", "all", 100, now, None).rows
    assert [row["id"] for row in rows] == [unknown.id]


def test_frozen_real_snapshot_matches_offline_all_modes(db_session: Session) -> None:
    import json
    from pathlib import Path

    import pytest

    from unspun.evaluation.feed_ranking import EventSample, rank_events

    root = Path(__file__).resolve().parents[2] / "docs/evaluations/m3b"
    snapshot = json.loads((root / "technical-candidates.json").read_text())
    annotations = json.loads((root / "technical-annotations.json").read_text())
    as_of = datetime.fromisoformat(snapshot["captured_at"])
    samples = [EventSample.model_validate(e) for e in snapshot["events"]]
    groups = {
        int(k): v
        for label in annotations["labels"]
        for k, v in label["article_publisher_groups"].items()
    }
    for sample in samples:
        event = Event(
            id=sample.id,
            title=sample.title,
            score_final=sample.score_final,
            first_seen_at=sample.first_seen_at,
            changed_at=sample.changed_at,
            public_impact={
                "status": sample.public_impact_status,
                "is_urgent": sample.public_impact_urgent,
                "evidence": [e.model_dump() for e in sample.public_impact_evidence],
                "assessed_at": sample.public_impact_assessed_at.isoformat()
                if sample.public_impact_assessed_at
                else None,
            },
        )
        db_session.add(event)
        for article in sample.articles:
            db_session.add(
                Article(
                    id=article.id,
                    source_id=article.source_id,
                    url=article.url,
                    title=article.title,
                    published_at=article.published_at,
                    fetched_at=article.fetched_at,
                    reported_at=article.reported_at,
                    reported_date=article.reported_date,
                    reported_precision=article.reported_precision or "unknown",
                    reported_basis=article.reported_basis,
                    publisher_group=groups[article.id],
                    content=article.impact_original_excerpt,
                    content_basis="original",
                    event=event,
                )
            )
    db_session.flush()
    for sort in ["newest", "hot", "important"]:
        for period in ["today", "24h", "7d", "all"]:
            expected = rank_events(samples, sort, period, as_of, article_publisher_groups=groups)
            actual = feed_page(db_session, sort, period, 100, as_of, None).rows
            assert [r["id"] for r in actual] == [r.id for r in expected], (sort, period)
            for row, reference in zip(actual, expected, strict=True):
                assert row["earliest_reported_at"] == reference.earliest
                assert row["earliest_reported_precision"] == reference.earliest_precision
                assert row["boosted"] == reference.public_impact_boosted
                if sort == "hot" and reference.metric is not None:
                    assert float(row["heat"]) == pytest.approx(reference.metric)


def test_cursor_validation_and_mutation_restart(db_session: Session) -> None:
    import base64
    import json

    import pytest
    from fastapi import HTTPException

    from unspun.core.feed_query import decode_cursor

    now = datetime.now(UTC)
    events = [
        Event(title="same-time", score_final=50, first_seen_at=now - timedelta(hours=1))
        for _ in range(3)
    ]
    db_session.add_all(events)
    db_session.flush()
    for event in events:
        db_session.add(
            Article(
                title="x",
                source_id="same",
                url=f"https://cursor/{event.id}",
                event=event,
                reported_at=now - timedelta(hours=1),
                reported_precision="time",
                fetched_at=now - timedelta(minutes=1),
            )
        )
    db_session.flush()
    first = feed_page(db_session, "important", "7d", 1, now, None)
    assert first.rows[0]["id"] == events[-1].id
    assert first.next_cursor
    for invalid in ["not-json", "x" * 2049]:
        with pytest.raises(HTTPException):
            decode_cursor(invalid, "important", "7d", now)
    with pytest.raises(HTTPException):
        decode_cursor(first.next_cursor, "hot", "7d", now)
    payload = json.loads(
        base64.urlsafe_b64decode(first.next_cursor + "=" * (-len(first.next_cursor) % 4))
    )
    for key in [True, "12", float("nan"), -1]:
        payload["key"][4] = key
        invalid = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
        with pytest.raises(HTTPException):
            decode_cursor(invalid, "important", "7d", now)
    # New observations beyond as_of cannot shift this page or appear in its DTO.
    db_session.add(
        Article(
            title="new",
            source_id="new",
            url="https://cursor/new",
            event=events[0],
            reported_at=now,
            reported_precision="time",
            fetched_at=now + timedelta(seconds=1),
        )
    )
    db_session.flush()
    second = feed_page(
        db_session, "important", "7d", 1, now + timedelta(seconds=2), first.next_cursor
    )
    assert second.as_of == now
    assert second.rows[0]["id"] == events[-2].id
    events[0].score_final = 90
    db_session.flush()
    with pytest.raises(HTTPException) as error:
        feed_page(db_session, "important", "7d", 1, now + timedelta(seconds=2), first.next_cursor)
    assert error.value.status_code == 409


def test_date_uncertainty_beijing_boundaries_and_bad_originals(db_session: Session) -> None:
    now = datetime(2026, 10, 14, 0, 30, tzinfo=UTC)
    event = Event(title="date-only", first_seen_at=now - timedelta(hours=1))
    unknown = Event(title="bad time", first_seen_at=now - timedelta(hours=1))
    db_session.add_all([event, unknown])
    db_session.flush()
    db_session.add(
        Article(
            source_id="s",
            url="https://dates/date",
            title="x",
            event=event,
            reported_date=now.date(),
            reported_precision="date",
            fetched_at=now,
        )
    )
    db_session.add(
        Article(
            source_id="s",
            url="https://dates/future",
            title="x",
            event=unknown,
            reported_at=now + timedelta(hours=1),
            reported_precision="time",
            fetched_at=now,
        )
    )
    db_session.flush()
    assert not feed_page(db_session, "newest", "today", 100, now, None).rows
    rows = feed_page(db_session, "newest", "all", 100, now, None).rows
    assert rows[0]["earliest_reported_at"] is None
    assert rows[0]["earliest_reported_date"] == now.date()
    assert rows[0]["earliest_reported_precision"] == "date"
    assert rows[-1]["invalid_time_count"] == 1


def test_urgent_requires_current_member_original_quotes(db_session: Session) -> None:
    now = datetime.now(UTC)
    urgent = Event(title="urgent", score_final=10, first_seen_at=now - timedelta(hours=1))
    product = Event(title="product", score_final=90, first_seen_at=now - timedelta(hours=1))
    db_session.add_all([urgent, product])
    db_session.flush()
    member = Article(
        source_id="s",
        url="https://impact/urgent",
        title="x",
        content="Serious harm happened today.",
        content_basis="original",
        event=urgent,
        reported_at=now - timedelta(hours=2),
        reported_precision="time",
        fetched_at=now - timedelta(minutes=1),
    )
    db_session.add_all(
        [
            member,
            Article(
                source_id="s",
                url="https://impact/product",
                title="x",
                event=product,
                reported_at=now - timedelta(hours=1),
                reported_precision="time",
                fetched_at=now - timedelta(minutes=1),
            ),
        ]
    )
    db_session.flush()
    urgent.public_impact = {
        "status": "supported",
        "is_urgent": True,
        "evidence": [{"article_id": member.id, "quote": "Serious harm happened today."}],
        "assessed_at": now.isoformat(),
    }
    db_session.flush()
    assert feed_page(db_session, "important", "7d", 100, now, None).rows[0]["id"] == urgent.id
    member.content = "Original was replaced."
    db_session.flush()
    assert feed_page(db_session, "important", "7d", 100, now, None).rows[0]["id"] == product.id
    member.content = "Serious harm happened today."
    member.reported_at = now - timedelta(hours=49)
    db_session.flush()
    assert feed_page(db_session, "important", "7d", 100, now, None).rows[0]["id"] == product.id


def test_malformed_stored_impact_falls_back_without_breaking_feed(db_session: Session) -> None:
    now = datetime.now(UTC)
    event = Event(
        title="malformed impact",
        score_final=20,
        first_seen_at=now - timedelta(hours=1),
        public_impact={
            "status": "supported",
            "is_urgent": True,
            "assessed_at": "garbage",
            "evidence": {"bad": "shape"},
        },
    )
    db_session.add_all(
        [
            event,
            Article(
                title="x",
                source_id="s",
                url="https://impact/invalid",
                event=event,
                reported_at=now - timedelta(hours=1),
                reported_precision="time",
                fetched_at=now,
            ),
        ]
    )
    db_session.flush()
    page = feed_page(db_session, "important", "7d", 100, now, None)
    assert page.rows[0]["boosted"] == 0


def test_brand_aliases_and_epoch_date_match_publication_contract(db_session: Session) -> None:
    now = datetime.now(UTC)
    event = Event(title="BBC sections", first_seen_at=now - timedelta(hours=1))
    epoch = Event(title="epoch date", first_seen_at=now - timedelta(hours=1))
    db_session.add_all([event, epoch])
    db_session.flush()
    for index, group in enumerate(["bbc.com", "bbc.co.uk"]):
        db_session.add(
            Article(
                title="x",
                source_id=f"bbc-{index}",
                url=f"https://brand/{index}",
                event=event,
                publisher_group=group,
                reported_at=now - timedelta(hours=1),
                reported_precision="time",
                fetched_at=now,
            )
        )
    db_session.add(
        Article(
            title="x",
            source_id="s",
            url="https://brand/epoch",
            event=epoch,
            reported_date=datetime(1970, 1, 1).date(),
            reported_precision="date",
            fetched_at=now,
        )
    )
    db_session.flush()
    assert feed_page(db_session, "hot", "7d", 100, now, None).rows[0]["active_publishers"] == 1
    rows = feed_page(db_session, "newest", "all", 100, now, None).rows
    assert rows[-1]["earliest_lower"] == datetime(1970, 1, 1, tzinfo=UTC)
    assert rows[-1]["earliest_reported_at"] is None


def test_api_dependency_keeps_one_snapshot_across_concurrent_scoring(db_session: Session) -> None:
    from sqlalchemy import create_engine, delete

    from unspun.api.events import get_db
    from unspun.core.config import get_settings

    # This isolated database test needs committed rows for a second connection.
    engine = create_engine(get_settings().database_url)
    now = datetime.now(UTC)
    with Session(engine) as writer:
        event = Event(title="snapshot race", score_final=40, first_seen_at=now - timedelta(hours=1))
        writer.add(event)
        writer.flush()
        event_id = event.id
        writer.add(
            Article(
                title="source",
                source_id="race",
                url=f"https://race/{event_id}",
                event=event,
                reported_at=now - timedelta(hours=1),
                reported_precision="time",
                fetched_at=now - timedelta(minutes=1),
            )
        )
        writer.commit()
        reader_generator = get_db()
        reader = next(reader_generator)
        try:
            page = feed_page(reader, "important", "7d", 100, now, None)
            event.score_final = 95
            writer.commit()
            snapshot = reader.get(Event, event_id)
            assert snapshot is not None and snapshot.score_final == 40
            assert next(row for row in page.rows if row["id"] == event_id)["metric"] == 40
        finally:
            reader_generator.close()
            writer.execute(delete(Article).where(Article.event_id == event_id))
            writer.execute(delete(Event).where(Event.id == event_id))
            writer.commit()
    engine.dispose()
