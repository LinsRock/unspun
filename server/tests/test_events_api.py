from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy.orm import Session

from unspun.api.app import app
from unspun.api.events import get_db, viewpoint_out
from unspun.core.models import Article, Event, EventViewpoint


@pytest.mark.anyio
async def test_events_newest_order_and_legacy_score_compatibility(db_session: Session) -> None:
    now = datetime.now(UTC)
    # 90 * 2^(-72/24) = 11.25, so the fresh 60 must rank first.
    old_high = Event(title="old-high", score_final=90.0, changed_at=now - timedelta(hours=72))
    fresh_low = Event(title="fresh-low", score_final=60.0, changed_at=now)
    unscored = Event(title="unscored", changed_at=now)
    old_high.first_seen_at = now - timedelta(days=1)
    fresh_low.first_seen_at = now - timedelta(hours=1)
    unscored.first_seen_at = now - timedelta(days=2)
    article = Article(
        source_id="bbc-world",
        url="https://example.com/x",
        title="orig title",
        title_zh="zh title",
        event=fresh_low,
        reported_at=now - timedelta(hours=1),
        reported_precision="time",
        fetched_at=now - timedelta(minutes=1),
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
            resp = await client.get("/api/events", params={"limit": 100, "range": "all"})
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


@pytest.mark.anyio
async def test_events_include_viewpoint_payload(db_session: Session) -> None:
    now = datetime.now(UTC)
    event = Event(
        title="with-vp", score_final=50.0, changed_at=now, first_seen_at=now - timedelta(minutes=1)
    )
    a1 = Article(
        source_id="bbc-world",
        url="https://example.com/vp1",
        title="t1",
        event=event,
        fetched_at=now - timedelta(minutes=1),
    )
    a2 = Article(
        source_id="caixin",
        url="https://example.com/vp2",
        title="t2",
        event=event,
        fetched_at=now - timedelta(minutes=1),
    )
    db_session.add_all([event, a1, a2])
    db_session.flush()
    payload = {
        "claims": [
            {"article_id": a1.id, "claim": "claim one"},
            {"article_id": a2.id, "claim": "claim two"},
        ],
        "disagreements": [{"point": "p", "claim_indexes": [0, 1]}],
    }
    event.viewpoint = EventViewpoint(payload=payload, input_fingerprint="f", model="m")
    db_session.flush()

    def override() -> Generator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = override
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/events", params={"limit": 100, "range": "all"})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    ours = next(e for e in resp.json()["events"] if e["id"] == event.id)
    vp = ours["viewpoint"]
    assert vp["model"] == "m"
    assert vp["claims"] == [{**c, "evidence_quote": None} for c in payload["claims"]]
    assert vp["disagreements"] == [{**d, "kind": None} for d in payload["disagreements"]]
    assert {c["article_id"] for c in vp["claims"]} <= {a["id"] for a in ours["articles"]}
    others = [e for e in resp.json()["events"] if e["id"] != event.id]
    assert all(e["viewpoint"] is None for e in others)


def test_viewpoint_out_tolerates_unreadable_payload(db_session: Session) -> None:
    event = Event(title="bad-vp")
    db_session.add(event)
    db_session.flush()
    row = EventViewpoint(
        event_id=event.id, payload={"claims": "garbage"}, input_fingerprint="f", model="m"
    )
    db_session.add(row)
    db_session.flush()
    assert viewpoint_out(row, {1}) is None


def test_viewpoint_out_drops_foreign_claims_and_remaps(db_session: Session) -> None:
    event = Event(title="vp-membership")
    db_session.add(event)
    db_session.flush()
    row = EventViewpoint(
        event_id=event.id,
        payload={
            "claims": [
                {"article_id": 1, "claim": "a"},
                {"article_id": 999, "claim": "left the event"},
                {"article_id": 2, "claim": "b"},
            ],
            "disagreements": [
                {"point": "kept", "claim_indexes": [0, 2]},
                {"point": "one side left", "claim_indexes": [1, 2]},
            ],
        },
        input_fingerprint="f",
        model="m",
    )
    db_session.add(row)
    db_session.flush()
    out = viewpoint_out(row, {1, 2})
    assert out is not None
    assert [c.article_id for c in out.claims] == [1, 2]
    # Index 2 remaps to 1 after the foreign claim is dropped; the point
    # referencing the dropped claim loses a side and is removed.
    assert [(d.point, d.claim_indexes) for d in out.disagreements] == [("kept", [0, 1])]


@pytest.mark.anyio
async def test_feed_defaults_validation_and_fixed_cursor_snapshot(db_session: Session) -> None:
    from unspun.api.events import get_feed_now

    now = datetime.now(UTC)
    recent = Event(title="recent original", first_seen_at=now - timedelta(hours=1))
    old = Event(title="late fetched old original", first_seen_at=now - timedelta(hours=1))
    db_session.add_all([recent, old])
    db_session.flush()
    db_session.add_all(
        [
            Article(
                title="source",
                source_id="bbc-world",
                url="https://defaults/recent",
                event=recent,
                reported_at=now - timedelta(days=1),
                reported_precision="time",
                fetched_at=now - timedelta(minutes=1),
            ),
            Article(
                title="source",
                source_id="bbc-world",
                url="https://defaults/old",
                event=old,
                reported_at=now - timedelta(days=30),
                reported_precision="time",
                fetched_at=now - timedelta(minutes=1),
            ),
            Article(
                title="future observation",
                source_id="bbc-world",
                url="https://defaults/future",
                event=recent,
                reported_at=now,
                reported_precision="time",
                fetched_at=now + timedelta(seconds=1),
            ),
        ]
    )
    db_session.flush()

    def override() -> Generator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = override
    app.dependency_overrides[get_feed_now] = lambda: now
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/events")
            assert response.status_code == 200
            data = response.json()
            assert data["sort"] == "newest" and data["range"] == "7d"
            assert data["as_of"] == now.isoformat().replace("+00:00", "Z")
            assert [row["id"] for row in data["events"]] == [recent.id]
            assert len(data["events"][0]["articles"]) == 1
            for invalid in [{"sort": "baseline"}, {"range": "30d"}, {"limit": 0}, {"limit": 101}]:
                assert (await client.get("/api/events", params=invalid)).status_code == 422
            assert (await client.get("/api/events", params={"cursor": "bad"})).status_code == 400
    finally:
        app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def feed_identity():
    from unspun.api.admin.auth import require_admin_identity

    app.dependency_overrides[require_admin_identity] = lambda: "owner"
    yield
    app.dependency_overrides.pop(require_admin_identity, None)
