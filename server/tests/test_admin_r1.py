"""R1 administration exposes actual stages and attempts behind existing auth."""

from collections.abc import Generator
from contextlib import contextmanager

import httpx
import pytest
from sqlalchemy.orm import Session

from unspun.api.admin import r1
from unspun.api.admin.auth import require_admin_identity
from unspun.api.app import app
from unspun.core.models import Article
from unspun.core.tasks import claim, enqueue


@pytest.mark.anyio
async def test_r1_admin_requires_existing_identity() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        assert (await client.get("/api/admin/r1/contents")).status_code == 503
        assert (await client.get("/api/admin/r1/tasks")).status_code == 503


@pytest.mark.anyio
async def test_r1_admin_stage_details_and_attempts_are_real(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.test_content_processing import persisted_content

    content = persisted_content(db_session)
    task_id = enqueue(
        db_session,
        queue="paid",
        kind="process_card",
        object_key="synthetic-admin-r1",
        input_fingerprint="synthetic",
        strategy_version="synthetic",
        payload={},
        article_id=content.article_id,
        source_id=content.source_id,
    )
    lease = claim(db_session, queue="paid", kinds={"process_card"}, worker="synthetic-admin")
    assert lease

    @contextmanager
    def scope() -> Generator[Session]:
        yield db_session

    monkeypatch.setattr(r1, "session_scope", scope)
    app.dependency_overrides[require_admin_identity] = lambda: "synthetic"
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            listed = (await client.get("/api/admin/r1/contents")).json()["items"]
            row = next(r for r in listed if r["id"] == content.article_id)
            assert row["current_material_id"] == content.material_id and row["derivations"] == []
            detail = (await client.get(f"/api/admin/r1/contents/{content.article_id}")).json()
            assert detail["materials"][0]["scope"] == "open_text_unit"
            assert detail["materials"][0]["access_status"] == "ok"
            attempts = (
                await client.get("/api/admin/r1/tasks", params={"article_id": content.article_id})
            ).json()["items"]
            task = next(t for t in attempts if t["id"] == task_id)
            assert task["status"] == "running" and task["attempt_records"][0]["status"] == "running"
            assert (await client.get("/api/admin/r1/tasks?queue=invalid")).status_code == 422
            legacy = Article(
                title="Legacy", url="https://example.org/legacy-admin-r1", source_id="synthetic"
            )
            db_session.add(legacy)
            db_session.flush()
            assert (await client.get(f"/api/admin/r1/contents/{legacy.id}")).status_code == 404
    finally:
        app.dependency_overrides.pop(require_admin_identity, None)
