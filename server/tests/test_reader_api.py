"""Existing Access and same-origin checks also protect the new reader writes."""

from collections.abc import Generator
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.orm import Session

from unspun.api.admin.auth import require_admin_identity
from unspun.api.app import app
from unspun.api.feed_preferences import get_write_db
from unspun.core.config import Settings, get_settings


@pytest.mark.anyio
async def test_reader_requires_access_identity_and_same_origin(db_session: Session) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        access_team_domain="synthetic.cloudflareaccess.com", access_audience="synthetic"
    )

    def db() -> Generator[Session]:
        yield db_session

    app.dependency_overrides[get_write_db] = db
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://test"
        ) as client:
            assert (await client.get("/api/interests")).status_code == 401
            app.dependency_overrides[require_admin_identity] = lambda: "synthetic"
            first = (await client.get("/api/interests")).json()
            assert first["version"] == 0 and first["interests"] == []
            body = {
                "version": 0,
                "mutation_id": str(uuid4()),
                "target": {"kind": "term", "value": "AI"},
            }
            assert (
                await client.put(
                    "/api/interests", json=body, headers={"Origin": "https://evil.example"}
                )
            ).status_code == 403
            added = await client.put(
                "/api/interests", json=body, headers={"Origin": "https://test"}
            )
            assert added.status_code == 200 and added.json()["version"] == 1
            revoked = await client.request(
                "DELETE",
                "/api/interests",
                json={**body, "version": 1, "mutation_id": str(uuid4())},
                headers={"Origin": "https://test"},
            )
            assert revoked.status_code == 200 and revoked.json()["interests"] == []
            replayed = await client.put(
                "/api/interests", json=body, headers={"Origin": "https://test"}
            )
            assert replayed.status_code == 200 and replayed.json()["interests"] == []
            assert replayed.json()["version"] == 2
    finally:
        for dependency in [get_settings, get_write_db, require_admin_identity]:
            app.dependency_overrides.pop(dependency, None)
