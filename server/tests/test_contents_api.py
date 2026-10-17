"""Authenticated detail reads stay free; explicit repeated guide requests deduplicate."""

from collections.abc import Generator

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_content_feed import enabled_sources, ready
from unspun.api.admin.auth import require_admin_identity
from unspun.api.app import app
from unspun.api.events import get_db
from unspun.api.feed_preferences import get_write_db
from unspun.core.config import Settings, get_settings
from unspun.core.models import ContentMaterial
from unspun.core.task_models import PipelineTask

__all__ = ["enabled_sources"]


@pytest.mark.anyio
async def test_gets_create_no_work_and_repeat_guide_request_reuses_task(
    db_session: Session, enabled_sources: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    article = ready(db_session)
    material = db_session.get(ContentMaterial, article.current_material_id)
    assert material
    material.paragraphs = [{"kind": "paragraph", "text": material.paragraphs[0]["text"] * 20}]
    # Publish a new reviewed result for the corrected material, with real version fencing.
    from tests.test_content_processing import FakeClient, approval, draft
    from unspun.pipeline.content_processing import apply_processing, load_content, organize

    material.input_fingerprint = "expanded-synthetic-material"
    db_session.flush()
    with Session() as detached:
        result = organize(
            detached,
            FakeClient(draft()),
            FakeClient(approval()),
            load_content(db_session, article.id),
        )
    apply_processing(db_session, result)

    def db() -> Generator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_write_db] = db
    app.dependency_overrides[require_admin_identity] = lambda: "synthetic"
    app.dependency_overrides[get_settings] = lambda: Settings()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://test"
        ) as client:
            assert (await client.get("/api/feed")).status_code == 200
            response = await client.get(f"/api/contents/{article.id}")
            assert response.status_code == 200
            assert response.json()["guide"]["status"] == "not_requested"
            assert db_session.scalar(select(func.count()).select_from(PipelineTask)) == 0
            assert (
                await client.post(
                    f"/api/contents/{article.id}/guide", headers={"Origin": "https://evil.example"}
                )
            ).status_code == 403
            first = await client.post(
                f"/api/contents/{article.id}/guide", headers={"Origin": "https://test"}
            )
            second = await client.post(
                f"/api/contents/{article.id}/guide", headers={"Origin": "https://test"}
            )
            assert first.status_code == second.status_code == 200
            assert first.json()["task_id"] == second.json()["task_id"]
            assert db_session.scalar(select(func.count()).select_from(PipelineTask)) == 1
    finally:
        for dependency in [get_db, get_write_db, require_admin_identity, get_settings]:
            app.dependency_overrides.pop(dependency, None)


@pytest.mark.anyio
async def test_production_cannot_turn_on_local_preview_with_only_a_flag(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from starlette.requests import Request

    from unspun.api.contents import local_preview

    monkeypatch.setattr(
        "unspun.api.contents.get_settings",
        lambda: Settings(
            r1_local_preview=True,
            admin_local_preview=True,
            database_url="postgresql://example/production",
        ),
    )
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as error:
        local_preview(Request({"type": "http", "client": ("127.0.0.1", 1)}), db_session)
    assert error.value.status_code == 503
