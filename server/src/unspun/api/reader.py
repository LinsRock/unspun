"""Authenticated R1 reader interests/feedback; GET never creates tasks or preferences."""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import Field
from sqlalchemy.orm import Session

from unspun.api.admin.auth import require_admin_identity
from unspun.api.events import get_db
from unspun.api.feed_preferences import Db, require_write
from unspun.core.reader import InterestTarget, Mutation, mutate, snapshot

router = APIRouter(dependencies=[Depends(require_admin_identity)])


class InterestInput(Mutation):
    target: InterestTarget


class FeedbackInput(Mutation):
    content_id: int = Field(gt=0, strict=True)
    value: Literal["interested", "not_interested"]


class FeedbackDelete(Mutation):
    content_id: int = Field(gt=0, strict=True)


class BrowseInput(Mutation):
    sort: Literal["recommended", "latest"]


@router.get("/api/reader-preferences")
@router.get("/api/interests")
@router.get("/api/feedback")
def get_reader(session: Annotated[Session, Depends(get_db)]) -> dict[str, Any]:
    return snapshot(session)


@router.put("/api/interests", dependencies=[Depends(require_write)])
def put_interest(body: InterestInput, session: Db) -> dict[str, Any]:
    return mutate(session, body, "interest", body.target.model_dump(), {"active": True})


@router.delete("/api/interests", dependencies=[Depends(require_write)])
def delete_interest(body: InterestInput, session: Db) -> dict[str, Any]:
    return mutate(session, body, "interest", body.target.model_dump(), None)


@router.put("/api/feedback", dependencies=[Depends(require_write)])
def put_feedback(body: FeedbackInput, session: Db) -> dict[str, Any]:
    return mutate(session, body, "feedback", {"content_id": body.content_id}, {"value": body.value})


@router.delete("/api/feedback", dependencies=[Depends(require_write)])
def delete_feedback(body: FeedbackDelete, session: Db) -> dict[str, Any]:
    return mutate(session, body, "feedback", {"content_id": body.content_id}, None)


@router.put("/api/reader-preferences", dependencies=[Depends(require_write)])
def put_browse(body: BrowseInput, session: Db) -> dict[str, Any]:
    return mutate(session, body, "browse", {}, {"sort": body.sort})
