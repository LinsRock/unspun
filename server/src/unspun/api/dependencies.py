"""Shared read snapshots, write transactions and same-origin write validation."""

from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from unspun.core.db import session_scope


def get_db() -> Generator[Session]:
    with session_scope() as session:
        # One request observes one MVCC snapshot across generation, ranking and DTO queries.
        session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        session.execute(text("SET TRANSACTION READ ONLY"))
        yield session


def get_write_db() -> Generator[Session]:
    with session_scope() as session:
        yield session


Db = Annotated[Session, Depends(get_write_db)]


def require_write(request: Request) -> None:
    # Avoid importing the admin router while shared dependencies are initialized.
    from unspun.api.admin.expenses import same_origin

    same_origin(request)
    if request.headers.get("sec-fetch-site") not in (None, "same-origin", "none"):
        raise HTTPException(403, "Same-origin request required")
