from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy.orm import Session

from unspun.api.app import app
from unspun.api.events import get_db
from unspun.core.config import Settings, get_settings
from unspun.core.models import Article, Event, PipelineRun


@pytest.fixture
def admin_client(db_session: Session) -> Generator[httpx.AsyncClient]:
    def override_db() -> Generator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = lambda: Settings(admin_local_preview=True)
    yield httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1")
    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_runs_half_open_paging_and_missing_history(
    db_session: Session, admin_client: httpx.AsyncClient
) -> None:
    now = datetime.now(UTC)
    old = PipelineRun(run_at=now - timedelta(hours=2), summarized=1)
    first = PipelineRun(run_at=now - timedelta(hours=1), summarized=2)
    second = PipelineRun(run_at=now - timedelta(hours=1), summarized=3)
    db_session.add_all([old, first, second])
    db_session.flush()
    start = (now - timedelta(hours=1)).isoformat()
    end = (now + timedelta(hours=1)).isoformat()
    async with admin_client as client:
        response = await client.get(
            "/api/admin/runs", params={"start": start, "end": end, "page_size": 1}
        )
        detail = await client.get(f"/api/admin/runs/{second.id}")
        missing = await client.get("/api/admin/runs/999999999")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 2
    assert body["items"][0]["id"] == second.id
    assert body["items"][0]["status"] is None
    assert body["items"][0]["ended_at"] is None
    assert body["items"][0]["duration_seconds"] is None
    assert detail.json()["summarized"] == 3
    assert detail.json()["missing_fields"]
    assert missing.status_code == 404


@pytest.mark.anyio
async def test_backlog_uses_pipeline_predicates(
    db_session: Session, admin_client: httpx.AsyncClient
) -> None:
    db_session.add_all(
        [
            Article(source_id="a3", url="https://example.org/a3-pending", title="pending"),
            Article(
                source_id="a3",
                url="https://example.org/a3-abandoned",
                title="abandoned",
                summary_failures=3,
            ),
            Article(
                source_id="a3",
                url="https://example.org/a3-embed",
                title="embedding",
                summary_zh="done",
            ),
            Event(title="a3 score pending"),
        ]
    )
    db_session.flush()
    async with admin_client as client:
        response = await client.get("/api/admin/backlog", params={"stage": "abandoned_summary"})
    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "current"
    assert body["counts"]["pending_summaries"] >= 1
    assert body["counts"]["pending_embeddings"] >= 1
    assert body["counts"]["pending_scores"] >= 1
    assert body["counts"]["abandoned_summaries"] >= 1
    assert any(item["title"] == "abandoned" for item in body["items"])


@pytest.mark.anyio
async def test_pending_backlog_order_matches_worker(
    db_session: Session, admin_client: httpx.AsyncClient
) -> None:
    first = Article(
        source_id="a3",
        url="https://example.org/a3-order-first",
        title="first worker item",
        published_at=datetime(2091, 1, 1, tzinfo=UTC),
        fetched_at=datetime(2090, 1, 1, tzinfo=UTC),
    )
    later = Article(
        source_id="a3",
        url="https://example.org/a3-order-later",
        title="later worker item",
        published_at=datetime(2090, 1, 1, tzinfo=UTC),
        fetched_at=datetime(2091, 1, 1, tzinfo=UTC),
    )
    db_session.add_all([first, later])
    db_session.flush()
    async with admin_client as client:
        response = await client.get("/api/admin/backlog", params={"page_size": 100})
    ids = [item["id"] for item in response.json()["items"]]
    assert ids.index(first.id) < ids.index(later.id)


@pytest.mark.anyio
async def test_configuration_never_returns_credentials(admin_client: httpx.AsyncClient) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        admin_local_preview=True,
        openrouter_api_key="secret-a3",
        database_url="postgresql://secret-a3@localhost/db",
    )
    async with admin_client as client:
        response = await client.get("/api/admin/configuration")
    assert response.status_code == 200
    body = response.json()
    assert body["credentials"]["openrouter_configured"] is True
    assert body["audit"]["status"] == "not_recorded"
    assert body["sources"]
    assert "secret-a3" not in response.text
    assert "database_url" not in response.text
