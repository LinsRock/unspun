from collections.abc import Generator
from datetime import UTC, date, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy.orm import Session

from unspun.api.app import app
from unspun.api.events import get_db
from unspun.core.models import Digest


@pytest.mark.anyio
async def test_digest_latest_history_and_errors(db_session: Session) -> None:
    now = datetime(2099, 1, 3, tzinfo=UTC)
    payload: dict[str, Any] = {
        "intro": "historical intro",
        "window_start": "2099-01-01T00:00:00Z",
        "window_end": "2099-01-02T00:00:00Z",
        "timezone": "Asia/Shanghai",
        "events": [],
    }
    db_session.add_all(
        [
            Digest(report_date=date(2099, 1, 2), payload=payload, generated_at=now),
            Digest(
                report_date=date(2099, 1, 3),
                payload={**payload, "intro": "latest intro"},
                generated_at=now,
            ),
            Digest(report_date=date(2099, 1, 4), kind="weekly", payload=payload, generated_at=now),
        ]
    )
    db_session.flush()

    def override() -> Generator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = override
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            latest = await client.get("/api/digest/latest")
            historical = await client.get("/api/digest/2099-01-02")
            missing = await client.get("/api/digest/2098-01-02")
            invalid = await client.get("/api/digest/2099-02-30")
            timestamp = await client.get("/api/digest/0")
            full_datetime = await client.get("/api/digest/2099-01-02T00:00:00Z")
    finally:
        app.dependency_overrides.clear()
    assert latest.status_code == 200
    assert latest.json()["report_date"] == "2099-01-03"
    assert latest.json()["kind"] == "daily"
    assert latest.json()["payload"]["intro"] == "latest intro"
    assert historical.status_code == 200
    assert historical.json()["payload"]["intro"] == "historical intro"
    assert historical.json()["generated_at"] == "2099-01-03T00:00:00Z"
    assert missing.status_code == 404
    assert invalid.status_code == 422
    assert timestamp.status_code == 422
    assert full_datetime.status_code == 422


@pytest.mark.anyio
async def test_latest_digest_returns_404_when_empty(db_session: Session) -> None:
    from sqlalchemy import delete

    db_session.execute(delete(Digest))  # Rolled back by the test fixture.

    def override() -> Generator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = override
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/digest/latest")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 404
