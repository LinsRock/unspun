"""Single-user feed state with atomic compare-and-set writes."""

from collections.abc import Generator
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from unspun.api.admin.auth import require_admin_identity
from unspun.api.admin.expenses import same_origin
from unspun.core.db import session_scope
from unspun.core.models import Event, EventReadState, FeedPreference

router = APIRouter(dependencies=[Depends(require_admin_identity)])


def get_write_db() -> Generator[Session]:
    with session_scope() as session:
        yield session


Db = Annotated[Session, Depends(get_write_db)]
Version = Annotated[int, Field(ge=0, le=2147483646, strict=True)]


class ReadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_read: StrictBool
    version: Version


class ReadState(ReadInput):
    read_at: datetime | None = None


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sort: Literal["newest", "hot", "important"] = "newest"
    range: Literal["today", "24h", "7d", "all"] = "7d"
    unread_only: StrictBool = False
    version: Version = 0


class PreferencesInput(Preferences):
    version: Version = Field(...)


def read_state(row: EventReadState | None) -> ReadState:
    return (
        ReadState(is_read=row.is_read, read_at=row.read_at, version=row.version)
        if row
        else ReadState(is_read=False, version=0)
    )


def preferences(row: FeedPreference | None) -> Preferences:
    return (
        Preferences.model_validate(
            {
                "sort": row.sort,
                "range": row.range,
                "unread_only": row.unread_only,
                "version": row.version,
            }
        )
        if row
        else Preferences()
    )


def require_write(request: Request) -> None:
    same_origin(request)
    if request.headers.get("sec-fetch-site") not in (None, "same-origin", "none"):
        raise HTTPException(403, "Same-origin request required")


@router.get("/api/feed-preferences", response_model=Preferences)
def get_preferences(session: Db) -> Preferences:
    return preferences(session.get(FeedPreference, 1))


@router.put(
    "/api/feed-preferences", response_model=Preferences, dependencies=[Depends(require_write)]
)
def put_preferences(body: PreferencesInput, session: Db) -> Preferences:
    values = {**body.model_dump(), "version": body.version + 1}
    if body.version == 0:
        stmt = (
            insert(FeedPreference)
            .values(id=1, **values)
            .on_conflict_do_nothing()
            .returning(FeedPreference.id)
        )
    else:
        stmt = (
            update(FeedPreference)
            .where(FeedPreference.id == 1, FeedPreference.version == body.version)
            .values(**values)
            .returning(FeedPreference.id)
        )
    if session.scalar(stmt) is None:
        current = preferences(session.get(FeedPreference, 1, populate_existing=True))
        raise HTTPException(409, detail={"current": current.model_dump(mode="json")})
    session.flush()
    return preferences(session.get(FeedPreference, 1, populate_existing=True))


@router.put(
    "/api/events/{event_id}/read-state",
    response_model=ReadState,
    dependencies=[Depends(require_write)],
)
def put_read_state(event_id: int, body: ReadInput, session: Db) -> ReadState:
    # Keep the parent alive through this transaction; deletes cannot race an insert.
    if (
        session.scalar(
            select(Event.id).where(Event.id == event_id).with_for_update(key_share=True, read=True)
        )
        is None
    ):
        raise HTTPException(404, "Event not found")
    values = {
        "is_read": body.is_read,
        "read_at": datetime.now(UTC) if body.is_read else None,
        "version": body.version + 1,
    }
    if body.version == 0:
        stmt = (
            insert(EventReadState)
            .values(event_id=event_id, **values)
            .on_conflict_do_nothing()
            .returning(EventReadState.event_id)
        )
    else:
        stmt = (
            update(EventReadState)
            .where(EventReadState.event_id == event_id, EventReadState.version == body.version)
            .values(**values)
            .returning(EventReadState.event_id)
        )
    if session.scalar(stmt) is None:
        current = read_state(session.get(EventReadState, event_id, populate_existing=True))
        raise HTTPException(409, detail={"current": current.model_dump(mode="json")})
    session.flush()
    return read_state(session.get(EventReadState, event_id, populate_existing=True))
