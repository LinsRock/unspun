from collections.abc import Generator

import httpx
import pytest
from sqlalchemy.orm import Session

from unspun.api.admin.auth import require_admin_identity
from unspun.api.app import app
from unspun.api.events import get_db
from unspun.api.reading import get_write_db
from unspun.core.models import Event


@pytest.mark.anyio
async def test_read_state_versions_filter_and_preferences(db_session: Session) -> None:
    event = Event(title="reading")
    db_session.add(event)
    db_session.flush()

    def override() -> Generator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = override
    app.dependency_overrides[get_write_db] = override
    app.dependency_overrides[require_admin_identity] = lambda: "owner"
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://test"
        ) as client:
            url = f"/api/events/{event.id}/read-state"
            headers = {"Origin": "https://test"}
            assert (await client.put(url, json={"is_read": True, "version": 0})).status_code == 403
            read = await client.put(url, json={"is_read": True, "version": 0}, headers=headers)
            assert read.status_code == 200
            assert read.json()["version"] == 1 and read.json()["read_at"]
            conflict = await client.put(url, json={"is_read": False, "version": 0}, headers=headers)
            assert conflict.status_code == 409 and conflict.json()["detail"]["current"]["is_read"]
            page = (await client.get("/api/events?range=all&unread_only=true&limit=1")).json()
            assert all(row["id"] != event.id for row in page["events"])
            unread = await client.put(url, json={"is_read": False, "version": 1}, headers=headers)
            assert unread.json()["read_at"] is None and unread.json()["version"] == 2
            assert (
                await client.put(
                    "/api/events/99999999/read-state",
                    json={"is_read": True, "version": 0},
                    headers=headers,
                )
            ).status_code == 404
            prefs = (await client.get("/api/feed-preferences")).json()
            assert prefs == {"sort": "newest", "range": "7d", "unread_only": False, "version": 0}
            saved = await client.put(
                "/api/feed-preferences",
                json={**prefs, "sort": "important", "unread_only": True},
                headers=headers,
            )
            assert saved.status_code == 200 and saved.json()["version"] == 1
            assert (
                await client.put("/api/feed-preferences", json=prefs, headers=headers)
            ).status_code == 409
            assert (await client.get("/api/feed-preferences")).json()["sort"] == "important"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_reading_requires_verified_identity() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as client:
        for method, url in [
            ("GET", "/api/feed-preferences"),
            ("GET", "/api/events"),
            ("PUT", "/api/feed-preferences"),
            ("PUT", "/api/events/1/read-state"),
        ]:
            assert (
                await client.request(method, url, json={"is_read": True, "version": 0})
            ).status_code in (401, 503)


def test_unread_filter_precedes_limit_and_new_articles_preserve_state(db_session: Session) -> None:
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import delete

    from unspun.core.feed_query import feed_page
    from unspun.core.models import Article, EventReadState

    now = datetime.now(UTC)
    events = [Event(title=f"filter-{i}", first_seen_at=now - timedelta(hours=1)) for i in range(3)]
    db_session.add_all(events)
    db_session.flush()
    for i, event in enumerate(events):
        db_session.add(
            Article(
                event_id=event.id,
                source_id="test",
                title="original",
                url=f"https://reading/{i}",
                reported_at=now - timedelta(minutes=i + 1),
                reported_precision="time",
                fetched_at=now - timedelta(seconds=10),
            )
        )
    db_session.add(EventReadState(event_id=events[0].id, is_read=True, read_at=now, version=1))
    db_session.flush()
    page = feed_page(db_session, "newest", "all", 1, now, None, True)
    assert page.rows[0]["id"] == events[1].id
    assert page.next_cursor
    next_page = feed_page(db_session, "newest", "all", 1, now, page.next_cursor, True)
    assert next_page.rows[0]["id"] == events[2].id
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as mismatch:
        feed_page(db_session, "newest", "all", 1, now, page.next_cursor, False)
    assert mismatch.value.status_code == 400
    db_session.add(
        Article(
            event_id=events[0].id,
            source_id="test",
            title="reprint",
            url="https://reading/new",
            fetched_at=now,
        )
    )
    db_session.flush()
    state = db_session.get(EventReadState, events[0].id)
    assert state and state.is_read
    deleted_id = events[0].id
    db_session.execute(delete(Article).where(Article.event_id == events[0].id))
    db_session.execute(delete(Event).where(Event.id == events[0].id))
    db_session.expire_all()
    assert db_session.get(EventReadState, deleted_id) is None


def test_competing_initial_read_writes_have_one_winner(db_session: Session) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from fastapi import HTTPException
    from sqlalchemy import delete

    from unspun.api.reading import ReadInput, put_read_state

    engine = db_session.get_bind().engine
    with Session(engine) as session:
        event = Event(title="concurrent-read")
        session.add(event)
        session.commit()
        event_id = event.id
    barrier = Barrier(2)

    def write(_: int) -> int:
        with Session(engine) as session:
            barrier.wait(timeout=5)
            try:
                put_read_state(event_id, ReadInput(is_read=True, version=0), session)
                session.commit()
                return 200
            except HTTPException as error:
                session.rollback()
                return error.status_code

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(write, range(2))) == [200, 409]
    finally:
        with Session(engine) as session:
            session.execute(delete(Event).where(Event.id == event_id))
            session.commit()


@pytest.mark.anyio
async def test_writes_validate_origin_fetch_metadata_and_input(db_session: Session) -> None:
    def override() -> Generator[Session]:
        yield db_session

    app.dependency_overrides[get_write_db] = override
    app.dependency_overrides[require_admin_identity] = lambda: "owner"
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://test"
        ) as client:
            body = {"sort": "newest", "range": "all", "unread_only": False, "version": 0}
            for headers in [
                {"Origin": "https://other"},
                {"Origin": "https://test", "Sec-Fetch-Site": "cross-site"},
                {"Origin": "https://test", "Sec-Fetch-Site": "same-site"},
            ]:
                assert (
                    await client.put("/api/feed-preferences", json=body, headers=headers)
                ).status_code == 403
            for invalid in [
                {**body, "sort": "other"},
                {**body, "unread_only": "true"},
                {**body, "version": -1},
                {**body, "version": True},
                {**body, "extra": "ignored"},
                {key: value for key, value in body.items() if key != "version"},
            ]:
                assert (
                    await client.put(
                        "/api/feed-preferences", json=invalid, headers={"Origin": "https://test"}
                    )
                ).status_code == 422
    finally:
        app.dependency_overrides.clear()
