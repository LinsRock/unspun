from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy.orm import Session

from unspun.api.app import app
from unspun.api.events import get_db
from unspun.core.models import Article, Event


@pytest.mark.anyio
async def test_events_ordered_by_decayed_score(db_session: Session) -> None:
    now = datetime.now(UTC)
    # 90 * 2^(-72/24) = 11.25, so the fresh 60 must rank first.
    old_high = Event(title="old-high", score_final=90.0, changed_at=now - timedelta(hours=72))
    fresh_low = Event(title="fresh-low", score_final=60.0, changed_at=now)
    unscored = Event(title="unscored", changed_at=now)
    article = Article(
        source_id="bbc-world",
        url="https://example.com/x",
        title="orig title",
        title_zh="zh title",
        event=fresh_low,
    )
    db_session.add_all([old_high, fresh_low, unscored, article])
    db_session.flush()
    ours = {old_high.id: "old-high", fresh_low.id: "fresh-low", unscored.id: "unscored"}

    def override() -> Generator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = override
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/events", params={"limit": 200})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    events = [e for e in resp.json()["events"] if e["id"] in ours]
    assert [ours[e["id"]] for e in events] == ["fresh-low", "old-high", "unscored"]

    fresh = events[0]
    assert fresh["score_decayed"] == pytest.approx(60.0, abs=0.5)
    assert fresh["articles"][0]["source_name"] == "BBC World"
    assert fresh["articles"][0]["url"] == "https://example.com/x"
    assert events[2]["score_final"] is None
