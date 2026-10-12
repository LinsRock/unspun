from datetime import UTC, datetime

import httpx
import pytest

from unspun.api.admin.auth import require_admin_identity
from unspun.api.admin.ranges import resolve_range
from unspun.api.app import app


def test_beijing_today_crosses_utc_date() -> None:
    now = datetime(2026, 10, 12, 1, 30, tzinfo=UTC)
    result = resolve_range(None, None, now)
    assert result.start.isoformat() == "2026-10-11T16:00:00+00:00"
    assert result.end == now


def test_explicit_range_is_half_open_and_clipped_to_snapshot() -> None:
    now = datetime(2026, 10, 12, 1, 30, tzinfo=UTC)
    result = resolve_range(
        datetime.fromisoformat("2026-10-11T00:00:00+08:00"),
        datetime.fromisoformat("2026-10-13T00:00:00+08:00"),
        now,
    )
    assert result.start.isoformat() == "2026-10-10T16:00:00+00:00"
    assert result.end == now


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2026-10-12T00:00:00", "2026-10-13T00:00:00+08:00"),
        ("2026-10-13T00:00:00+08:00", "2026-10-12T00:00:00+08:00"),
    ],
)
def test_invalid_range_rejected(start: str, end: str) -> None:
    with pytest.raises(ValueError):
        resolve_range(
            datetime.fromisoformat(start),
            datetime.fromisoformat(end),
            datetime(2026, 10, 14, tzinfo=UTC),
        )


@pytest.mark.anyio
async def test_range_endpoint_rejects_invalid_query() -> None:
    app.dependency_overrides[require_admin_identity] = lambda: "test-user"
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            for params in (
                {"start": "2026-10-12T00:00:00+08:00"},
                {"page": "0"},
                {"page_size": "101"},
                {"sort": "drop table"},
                {
                    "start": "2026-10-12T00:00:00+08:00",
                    "end": "2026-10-11T00:00:00+08:00",
                },
            ):
                response = await client.get("/api/admin/range", params=params)
                assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()
