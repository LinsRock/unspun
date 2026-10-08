import httpx
import pytest

from unspun.api.app import app


@pytest.mark.anyio
async def test_health_reports_version_and_db_state() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/health")
    assert resp.status_code == 200
    body: dict[str, str] = resp.json()
    assert body["version"] == "dev"
    # No database in unit tests: the endpoint must degrade, not crash.
    assert body["status"] in ("ok", "degraded")
    assert body["database"] in ("ok", "error")
