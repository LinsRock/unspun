"""Single-user feed preferences with atomic compare-and-set writes."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert

from unspun.api.admin.auth import require_admin_identity
from unspun.api.dependencies import Db, require_write
from unspun.core.models import FeedPreference

router = APIRouter(dependencies=[Depends(require_admin_identity)])


Version = Annotated[int, Field(ge=0, le=2147483646, strict=True)]


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sort: Literal["newest", "hot", "important"] = "newest"
    range: Literal["today", "24h", "7d", "all"] = "7d"
    version: Version = 0


class PreferencesInput(Preferences):
    version: Version = Field(...)


def preferences(row: FeedPreference | None) -> Preferences:
    return (
        Preferences.model_validate(
            {
                "sort": row.sort,
                "range": row.range,
                "version": row.version,
            }
        )
        if row
        else Preferences()
    )


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
