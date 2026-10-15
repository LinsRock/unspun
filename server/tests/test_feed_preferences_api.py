from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import delete, inspect
from sqlalchemy.orm import Session

from unspun.api.admin.auth import require_admin_identity
from unspun.api.app import app
from unspun.api.events import get_db
from unspun.api.feed_preferences import PreferencesInput, get_write_db, put_preferences
from unspun.core.models import Event, FeedPreference


@pytest.fixture
def authorized_db(db_session: Session) -> Generator[Session]:
    def override() -> Generator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = override
    app.dependency_overrides[get_write_db] = override
    app.dependency_overrides[require_admin_identity] = lambda: "owner"
    try:
        yield db_session
    finally:
        app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_preferences_defaults_persistence_and_conflict(authorized_db: Session) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as client:
        prefs = (await client.get("/api/feed-preferences")).json()
        assert prefs == {"sort": "newest", "range": "7d", "version": 0}
        headers = {"Origin": "https://test"}
        saved = await client.put(
            "/api/feed-preferences",
            json={**prefs, "sort": "important", "range": "all"},
            headers=headers,
        )
        assert saved.status_code == 200
        assert saved.json() == {"sort": "important", "range": "all", "version": 1}
        conflict = await client.put("/api/feed-preferences", json=prefs, headers=headers)
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["current"] == saved.json()
        assert (await client.get("/api/feed-preferences")).json() == saved.json()
        updated = await client.put(
            "/api/feed-preferences", json={**saved.json(), "range": "today"}, headers=headers
        )
        assert updated.status_code == 200 and updated.json()["version"] == 2


@pytest.mark.anyio
async def test_preferences_require_verified_identity() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as client:
        for method, url in [
            ("GET", "/api/feed-preferences"),
            ("GET", "/api/events"),
            ("PUT", "/api/feed-preferences"),
        ]:
            response = await client.request(
                method, url, json={"sort": "newest", "range": "7d", "version": 0}
            )
            assert response.status_code in (401, 503)


@pytest.mark.anyio
async def test_preferences_validate_origin_metadata_and_input(authorized_db: Session) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as client:
        body = {"sort": "newest", "range": "all", "version": 0}
        for headers in [
            {},
            {"Origin": "https://other"},
            {"Origin": "https://test", "Sec-Fetch-Site": "cross-site"},
            {"Origin": "https://test", "Sec-Fetch-Site": "same-site"},
        ]:
            assert (
                await client.put("/api/feed-preferences", json=body, headers=headers)
            ).status_code == 403
        for invalid in [
            {**body, "sort": "other"},
            {**body, "range": "forever"},
            {**body, "version": -1},
            {**body, "version": True},
            {**body, "unread_only": True},
            {"sort": "newest", "range": "7d"},
        ]:
            assert (
                await client.put(
                    "/api/feed-preferences", json=invalid, headers={"Origin": "https://test"}
                )
            ).status_code == 422


@pytest.mark.anyio
async def test_reading_state_is_absent_and_legacy_filter_does_not_hide_events(
    authorized_db: Session,
) -> None:
    from datetime import UTC, datetime, timedelta

    event = Event(title="remains visible", first_seen_at=datetime.now(UTC) - timedelta(minutes=1))
    authorized_db.add(event)
    authorized_db.flush()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as client:
        for suffix in ["", "&unread_only=true"]:
            response = await client.get("/api/events?range=all" + suffix)
            assert response.status_code == 200
            row = next(row for row in response.json()["events"] if row["id"] == event.id)
            assert not {"is_read", "read_at", "read_version"} & row.keys()
        response = await client.put(
            f"/api/events/{event.id}/read-state", json={"is_read": True, "version": 0}
        )
        assert response.status_code == 404
    assert not inspect(authorized_db.get_bind()).has_table("event_read_states")


def test_competing_initial_preference_writes_have_one_winner(db_session: Session) -> None:
    engine = db_session.get_bind().engine
    with Session(engine) as session:
        if session.get(FeedPreference, 1) is not None:
            pytest.skip("concurrency test requires an empty isolated preferences table")
    barrier = Barrier(2)

    def write(_: int) -> int:
        with Session(engine) as session:
            barrier.wait(timeout=5)
            try:
                put_preferences(PreferencesInput(sort="hot", range="24h", version=0), session)
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
            session.execute(delete(FeedPreference).where(FeedPreference.id == 1))
            session.commit()
