"""Limited production reading uses the ordinary identity, qualification and reader APIs."""

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from tests.test_content_feed import enabled_sources as enabled_sources
from tests.test_content_feed import ready
from tests.test_hybrid_feed import hybrid as hybrid
from unspun.api.admin import auth
from unspun.api.app import app
from unspun.api.events import get_db
from unspun.api.feed_preferences import get_write_db
from unspun.core.config import Settings, get_settings
from unspun.core.task_models import PipelineTask
from unspun.pipeline.content_processing import load_content, processing_fingerprint


@pytest.fixture
def identity(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class LocalKeys:
        def get_signing_key_from_jwt(self, token: str) -> SimpleNamespace:
            return SimpleNamespace(key=key.public_key())

    def local_keys(domain: str) -> LocalKeys:
        return LocalKeys()

    monkeypatch.setattr(auth, "_jwk_client", local_keys)
    settings = get_settings()
    monkeypatch.setattr(settings, "admin_local_preview", False)
    monkeypatch.setattr(settings, "r1_local_preview", False)
    monkeypatch.setattr(settings, "access_team_domain", "fixture.cloudflareaccess.com")
    monkeypatch.setattr(settings, "access_audience", "limited-reading")
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "iss": "https://fixture.cloudflareaccess.com",
            "aud": ["limited-reading"],
            "sub": "isolated-reader",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        key,
        algorithm="RS256",
    )
    return {"Cf-Access-Jwt-Assertion": token, "Origin": "https://test"}


@pytest.mark.anyio
@pytest.mark.parametrize("mixed,home", [(False, False), (False, True), (True, False), (True, True)])
async def test_formal_home_requires_both_switches_and_identity(
    monkeypatch: pytest.MonkeyPatch, identity: dict[str, str], mixed: bool, home: bool
) -> None:
    assert Settings.model_fields["r2_discover_home_enabled"].default is False
    monkeypatch.setattr(get_settings(), "r2_hybrid_enabled", mixed)
    monkeypatch.setattr(get_settings(), "r2_discover_home_enabled", home)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as client:
        for headers in ({}, {**identity, "Cf-Access-Jwt-Assertion": "invalid"}):
            assert (
                await client.get("/api/reading-capabilities", headers=headers)
            ).status_code == 401
        response = await client.get("/api/reading-capabilities", headers=identity)
        assert response.status_code == 200
        assert response.json() == {
            "hybrid": mixed,
            "topic_preferences": False,
            "home": "discover" if mixed and home else "events",
            "engineering_preview": False,
        }


@pytest.mark.anyio
async def test_content_only_reads_and_rollback_preserve_tasks_and_reader(
    db_session: Session,
    hybrid: None,
    identity: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    items = [ready(db_session, age=age) for age in (1, 2, 3)]
    for article, status in zip(items, ("pending", "retry_wait", "budget_deferred"), strict=True):
        db_session.add(
            PipelineTask(
                queue="guide",
                kind="process_guide",
                object_key=f"content:{article.id}",
                article_id=article.id,
                input_fingerprint=processing_fingerprint(
                    load_content(db_session, article.id), "guide"
                ),
                strategy_version="engineering-fixture",
                dedupe_key=f"retained-guide:{article.id}",
                payload={},
                status=status,
                due_at=datetime.now(UTC) - timedelta(hours=1),
            )
        )
    db_session.flush()

    def database() -> Generator[Session]:
        yield db_session

    monkeypatch.setitem(app.dependency_overrides, get_db, database)
    monkeypatch.setitem(app.dependency_overrides, get_write_db, database)
    monkeypatch.setattr(get_settings(), "r2_discover_home_enabled", True)
    statements: list[str] = []

    def capture(
        conn: Connection, cursor: Any, statement: str, parameters: Any, context: Any, many: bool
    ) -> None:
        statements.append(statement)

    def protected() -> dict[str, list[Any]]:
        return {
            table: list(db_session.scalars(text(f"SELECT to_jsonb(t) FROM {table} t")))
            for table in (
                "pipeline_tasks",
                "task_attempts",
                "billed_requests",
                "llm_usage",
                "budget_policy",
                "budget_carry",
                "topics",
                "topic_preferences",
            )
        }

    before = protected()
    connection = db_session.connection()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test", headers=identity
    ) as client:
        event.listen(connection, "before_cursor_execute", capture)
        try:
            for sort in ("recommended", "latest"):
                params: dict[str, Any] = {"mode": "mixed", "sort": sort, "limit": 2}
                first = (await client.get("/api/feed", params=params)).json()
                assert first["recall"]["topic_candidates"] == 0
                assert all(item["type"] == "content" for item in first["items"])
                params["cursor"] = first["next_cursor"]
                second = (await client.get("/api/feed", params=params)).json()
                assert second == (await client.get("/api/feed", params=params)).json()
                assert len({item["id"] for p in (first, second) for item in p["items"]}) == 3
            for article in items:
                detail = await client.get(f"/api/contents/{article.id}")
                assert detail.status_code == 200
                assert detail.json()["guide"]["task_id"] is not None
                assert detail.json()["guide"]["requestable"] is False
            for path in ("/api/topic-preferences", f"/api/topics/{uuid4()}"):
                assert (await client.get(path)).status_code == 404
            assert (await client.get("/api/reader-preferences")).json()["version"] == 0
        finally:
            event.remove(connection, "before_cursor_execute", capture)
        assert all(sql.lstrip().upper().startswith(("SELECT", "WITH")) for sql in statements)
        state = (
            await client.put(
                "/api/feedback",
                json={
                    "version": 0,
                    "mutation_id": str(uuid4()),
                    "content_id": items[0].id,
                    "value": "interested",
                },
            )
        ).json()
        assert state["version"] == 1 and state["feedback"][0]["value"] == "interested"
        monkeypatch.setattr(get_settings(), "r2_discover_home_enabled", False)
        assert (await client.get("/api/reading-capabilities")).json()["home"] == "events"
        assert (await client.get("/api/feed?mode=mixed")).status_code == 200
        monkeypatch.setattr(get_settings(), "r2_hybrid_enabled", False)
        assert (await client.get("/api/feed?mode=mixed")).status_code == 404
        assert (await client.get("/api/feed")).json()["ranking_version"] == "r1-reader-v1"
        assert (await client.get(f"/api/contents/{items[0].id}")).status_code == 200
        assert (await client.get("/api/reader-preferences")).json() == state
        removed = await client.request(
            "DELETE",
            "/api/feedback",
            json={
                "version": 1,
                "mutation_id": str(uuid4()),
                "content_id": items[0].id,
            },
        )
        assert removed.status_code == 200 and removed.json()["feedback"] == []
        assert (await client.get("/api/events")).status_code == 200
        assert (await client.get("/api/digest")).status_code in (200, 404)
    assert protected() == before
