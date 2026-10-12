import csv
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from io import StringIO

import httpx
import pytest
from sqlalchemy.orm import Session

from unspun.api.admin import exports
from unspun.api.admin.auth import require_admin_identity
from unspun.api.admin.exports import csv_lines, safe_cell
from unspun.api.app import app
from unspun.core.models import Article


def test_csv_formula_injection_is_neutralized() -> None:
    for value in ("=1+1", "+cmd", "-1+2", "@SUM(A1)", " \t=1+1"):
        assert safe_cell(value).startswith("'")
    assert safe_cell("ordinary") == "ordinary"


def test_csv_export_caps_rows_and_quotes_fields() -> None:
    lines = list(
        csv_lines([{"title": "a,b"}, {"title": "=1"}, {"title": "third"}], ["title"], limit=2)
    )
    rows = list(csv.reader(StringIO("".join(lines))))
    assert rows == [["title"], ["a,b"], ["'=1"]]


@pytest.mark.anyio
async def test_article_export_reuses_list_filters(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime.now(UTC)
    source_id = f"csv-{now.timestamp()}"
    db_session.add_all(
        [
            Article(
                source_id=source_id,
                url=f"https://example.com/yes-{source_id}",
                title="=wanted",
                fetched_at=now,
            ),
            Article(
                source_id=source_id,
                url=f"https://example.com/no-{source_id}",
                title="unrelated",
                fetched_at=now,
            ),
        ]
    )
    db_session.flush()

    @contextmanager
    def local_session() -> Generator[Session]:
        yield db_session

    monkeypatch.setattr(exports, "session_scope", local_session)
    app.dependency_overrides[require_admin_identity] = lambda: "test-user"
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/admin/articles/export.csv",
                params={
                    "start": (now - timedelta(minutes=1)).isoformat(),
                    "end": (now + timedelta(seconds=1)).isoformat(),
                    "source_id": source_id,
                    "keyword": "=wanted",
                },
            )
        assert response.status_code == 200
        rows = list(csv.DictReader(StringIO(response.text)))
        assert len(rows) == 1
        assert rows[0]["title"] == "'=wanted"
    finally:
        app.dependency_overrides.clear()
