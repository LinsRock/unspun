from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from unspun.core.config import get_settings


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def db_session() -> Generator[Session]:
    """Session on the migrated database, rolled back after each test.

    Skips when no database is reachable or not migrated (plain local runs);
    CI provides a Postgres service and runs `alembic upgrade head` first.
    """
    engine = create_engine(get_settings().database_url)
    try:
        conn = engine.connect()
    except OperationalError:
        pytest.skip("database not available")
    has_schema = inspect(conn).has_table("articles")
    conn.rollback()  # inspect() autobegins; clear it before our own begin()
    if not has_schema:
        conn.close()
        pytest.skip("schema not migrated; run `uv run alembic upgrade head`")
    trans = conn.begin()
    session = Session(bind=conn)
    try:
        yield session
    finally:
        session.close()
        trans.rollback()
        conn.close()
        engine.dispose()
