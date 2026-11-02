"""Retired public reading routes cannot expose or mutate retained historical rows."""

from datetime import UTC, date, datetime

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from unspun.api.app import app
from unspun.core.models import Digest, Event, FeedPreference


@pytest.mark.anyio
async def test_retired_routes_are_absent_and_stored_history_is_unchanged(
    db_session: Session,
) -> None:
    db_session.add_all(
        [
            Event(title="Retained history"),
            Digest(
                report_date=date(2099, 1, 1),
                payload={"original": True},
                generated_at=datetime.now(UTC),
            ),
            FeedPreference(id=1, sort="hot", range="all", version=7),
        ]
    )
    db_session.flush()
    tables = ("events", "digests", "feed_preferences", "llm_usage", "billed_requests")

    def snapshot() -> dict[str, list[object]]:
        return {
            name: list(db_session.scalars(text(f"SELECT to_jsonb(t) FROM {name} t")))
            for name in tables
        }

    before = snapshot()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as client:
        for path in (
            "/api/events",
            "/api/digest/latest",
            "/api/digest/2099-01-01",
            "/api/feed-preferences",
        ):
            assert (await client.get(path)).status_code == 404
        assert (await client.put("/api/feed-preferences", json={"version": 7})).status_code == 404
    assert snapshot() == before
