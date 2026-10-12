from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from unspun.api.admin import auth
from unspun.api.app import app
from unspun.core.config import Settings, get_settings


@pytest.mark.anyio
async def test_admin_range_requires_verified_identity() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/admin/range")
    assert response.status_code in (401, 503)


@pytest.mark.anyio
async def test_spoofed_access_email_does_not_authorize_admin() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/admin/range", headers={"Cf-Access-Authenticated-User-Email": "owner@example.com"}
        )
    assert response.status_code in (401, 503)


@pytest.mark.anyio
async def test_local_preview_requires_explicit_flag_and_loopback() -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(admin_local_preview=True)
    try:
        local = httpx.ASGITransport(app=app, client=("127.0.0.1", 1234))
        remote = httpx.ASGITransport(app=app, client=("198.51.100.5", 1234))
        async with httpx.AsyncClient(transport=local, base_url="http://test") as client:
            assert (await client.get("/api/admin/range")).status_code == 200
        async with httpx.AsyncClient(transport=remote, base_url="http://test") as client:
            assert (await client.get("/api/admin/range")).status_code == 503
    finally:
        app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_signed_access_token_checks_audience_and_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()

    class FakeJwkClient:
        def get_signing_key_from_jwt(self, token: str) -> SimpleNamespace:
            return SimpleNamespace(key=public_key)

    def fake_client(domain: str) -> FakeJwkClient:
        return FakeJwkClient()

    monkeypatch.setattr(auth, "_jwk_client", fake_client)
    app.dependency_overrides[get_settings] = lambda: Settings(
        access_team_domain="team.cloudflareaccess.com", access_audience="correct-audience"
    )
    now = datetime.now(UTC)

    def assertion(audience: str, expiry: datetime) -> str:
        return jwt.encode(
            {
                "aud": [audience],
                "exp": expiry,
                "iat": now,
                "iss": "https://team.cloudflareaccess.com",
                "sub": "account-1",
            },
            private_key,
            algorithm="RS256",
            headers={"kid": "test-key"},
        )

    transport = httpx.ASGITransport(app=app, client=("198.51.100.5", 1234))
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            for audience, expiry, expected in (
                ("correct-audience", now + timedelta(minutes=5), 200),
                ("wrong-audience", now + timedelta(minutes=5), 401),
                ("correct-audience", now - timedelta(minutes=5), 401),
            ):
                response = await client.get(
                    "/api/admin/range",
                    headers={"Cf-Access-Jwt-Assertion": assertion(audience, expiry)},
                )
                assert response.status_code == expected
    finally:
        app.dependency_overrides.clear()
