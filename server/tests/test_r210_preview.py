"""The separate preview adapter must remain isolated and zero-task."""

from collections.abc import Generator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from unspun.api.app import app as production_app
from unspun.api.events import get_db
from unspun.api.feed_preferences import get_write_db
from unspun.core.billing_models import BilledRequest, BudgetPolicy
from unspun.core.config import get_settings
from unspun.core.sources import load_sources
from unspun.core.task_models import PipelineTask
from unspun.core.topic_synthesis import qualified_topic_text
from unspun.evaluation.preview_topics import create_app, groups, require_environment, seed


def settings(monkeypatch: pytest.MonkeyPatch) -> None:
    configuration = get_settings()
    for name, value in {
        "database_url": "postgresql+psycopg://unspun:unspun@127.0.0.1/unspun_r210_preview_test",
        "admin_local_preview": True,
        "r2_hybrid_enabled": True,
        "r2_topic_preferences_enabled": True,
        "r2_topic_publication_enabled": False,
        "r2_member_processing_enabled": False,
        "r2_synthesis_enabled": False,
        "r1_worker_enabled": False,
        "r1_local_preview": False,
        "openrouter_api_key": "",
    }.items():
        monkeypatch.setattr(configuration, name, value)


@pytest.mark.parametrize(
    "name,value",
    [
        ("database_url", "postgresql+psycopg://unspun:unspun@localhost/unspun"),
        ("database_url", "postgresql+psycopg://unspun:unspun@remote/unspun_r210_preview_test"),
        ("admin_local_preview", False),
        ("r1_worker_enabled", True),
        ("r2_member_processing_enabled", True),
        ("r2_synthesis_enabled", True),
        ("r2_topic_publication_enabled", True),
        ("openrouter_api_key", "fixture-key"),
    ],
)
def test_preview_fails_closed(monkeypatch: pytest.MonkeyPatch, name: str, value: object) -> None:
    settings(monkeypatch)
    monkeypatch.setattr(get_settings(), name, value)
    with pytest.raises(RuntimeError, match="isolated loopback"):
        require_environment()


@pytest.fixture
def preview(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    settings(monkeypatch)
    monkeypatch.setattr(
        "unspun.evaluation.preview_topics.get_engine", lambda: db_session.get_bind()
    )
    seed()
    application = create_app()

    def database() -> Generator[Session]:
        yield db_session

    for application_with_routes in (application, production_app):
        monkeypatch.setitem(application_with_routes.dependency_overrides, get_db, database)
        monkeypatch.setitem(application_with_routes.dependency_overrides, get_write_db, database)
    return application


@pytest.mark.anyio
async def test_real_sql_preview_paging_preferences_and_no_tasks(
    preview: FastAPI, db_session: Session
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=preview),
        base_url="http://127.0.0.1",
        headers={"Origin": "http://127.0.0.1"},
    ) as client:
        first = (await client.get("/api/feed?mode=mixed&limit=10")).json()
        assert first["engineering_preview"] is True
        assert first["next_cursor"]
        second = (
            await client.get(
                "/api/feed", params={"mode": "mixed", "limit": 10, "cursor": first["next_cursor"]}
            )
        ).json()
        rows = first["items"] + second["items"]
        assert len(rows) == 14 and len({(r["type"], r["id"]) for r in rows}) == 14
        topic = next(r for r in rows if r["type"] == "topic")
        assert topic["topic"]["engineering_preview"] is True
        detail = (await client.get(f"/api/topics/{topic['id']}")).json()
        assert detail["related"] and detail["engineering_preview"]
        body = {
            "version": 0,
            "mutation_id": str(uuid4()),
            "target": {"type": "topic", "id": topic["id"]},
        }
        changed = await client.put("/api/topic-follows", json=body)
        assert changed.status_code == 200
        assert changed.json()["version"] == 1
        conflict = await client.put(
            "/api/topic-follows", json={**body, "mutation_id": str(uuid4())}
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["current"]["topic_preferences"][0]["followed"] is True
        assert (
            await client.get(
                "/api/feed", params={"mode": "mixed", "limit": 10, "cursor": first["next_cursor"]}
            )
        ).status_code == 409
        assert (await client.post("/api/contents/9013/guide")).status_code == 403
        assert (await client.get("/api/contents/9013")).json()["guide"]["requestable"] is False
    for model in (PipelineTask, BilledRequest, BudgetPolicy):
        assert db_session.scalar(select(func.count()).select_from(model)) == 0
    for group in groups():
        assert (
            qualified_topic_text(
                db_session, UUID(group["topic_id"]), sources=load_sources(), now=datetime.now(UTC)
            )
            is None
        )


@pytest.mark.anyio
async def test_preview_rejects_nonloopback_and_admin(preview: FastAPI) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=preview, client=("10.0.0.1", 1234)),
        base_url="http://127.0.0.1",
        headers={"Origin": "http://127.0.0.1"},
    ) as client:
        assert (await client.get("/api/reading-capabilities")).status_code == 403
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=preview),
        base_url="http://127.0.0.1",
        headers={"Origin": "http://127.0.0.1"},
    ) as client:
        assert (await client.get("/api/admin/overview")).status_code == 403


@pytest.mark.anyio
async def test_preview_lan_writes_still_require_same_origin(preview: FastAPI) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=preview), base_url="http://192.168.1.10:5178"
    ) as client:
        body = {"version": 0, "mutation_id": str(uuid4()), "sort": "latest"}
        assert (
            await client.put(
                "/api/reader-preferences", json=body, headers={"Origin": "http://other.invalid"}
            )
        ).status_code == 403
        assert (
            await client.put(
                "/api/reader-preferences",
                json=body,
                headers={"Origin": "http://192.168.1.10:5178", "Sec-Fetch-Site": "cross-site"},
            )
        ).status_code == 403
        assert (
            await client.put(
                "/api/reader-preferences",
                json=body,
                headers={"Origin": "http://192.168.1.10:5178", "Sec-Fetch-Site": "same-origin"},
            )
        ).status_code == 200
