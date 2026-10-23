"""Authenticated R1 reader interests/feedback; GET never creates tasks or preferences."""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import Field
from sqlalchemy.orm import Session

from unspun.api.admin.auth import require_admin_identity
from unspun.api.events import get_db
from unspun.api.feed_preferences import Db, require_write
from unspun.core.reader import InterestTarget, Mutation, mutate, snapshot
from unspun.core.reader_targets import FeedbackTarget, TopicTarget, require_topic_preferences

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


class TopicFollowInput(Mutation):
    target: TopicTarget


class TargetFeedbackDelete(Mutation):
    target: FeedbackTarget


class TargetFeedbackInput(TargetFeedbackDelete):
    value: Literal["interested", "not_interested"]


@router.get("/api/topic-preferences", dependencies=[Depends(require_topic_preferences)])
def get_topic_preferences(session: Annotated[Session, Depends(get_db)]) -> dict[str, Any]:
    return snapshot(session, include_topics=True)


@router.put(
    "/api/topic-follows", dependencies=[Depends(require_write), Depends(require_topic_preferences)]
)
def put_topic_follow(body: TopicFollowInput, session: Db) -> dict[str, Any]:
    return mutate(
        session,
        body,
        "topic_follow",
        body.target.model_dump(mode="json"),
        {"active": True},
        include_topics=True,
    )


@router.delete(
    "/api/topic-follows", dependencies=[Depends(require_write), Depends(require_topic_preferences)]
)
def delete_topic_follow(body: TopicFollowInput, session: Db) -> dict[str, Any]:
    return mutate(
        session,
        body,
        "topic_follow",
        body.target.model_dump(mode="json"),
        None,
        include_topics=True,
    )


def target_feedback(
    body: TargetFeedbackDelete, session: Session, value: dict[str, Any] | None
) -> dict[str, Any]:
    if body.target.type == "content":
        kind, target = "feedback", {"content_id": body.target.id}
    else:
        kind, target = "topic_feedback", body.target.model_dump(mode="json")
    return mutate(session, body, kind, target, value, include_topics=True)


@router.put(
    "/api/target-feedback",
    dependencies=[Depends(require_write), Depends(require_topic_preferences)],
)
def put_target_feedback(body: TargetFeedbackInput, session: Db) -> dict[str, Any]:
    return target_feedback(body, session, {"value": body.value})


@router.delete(
    "/api/target-feedback",
    dependencies=[Depends(require_write), Depends(require_topic_preferences)],
)
def delete_target_feedback(body: TargetFeedbackDelete, session: Db) -> dict[str, Any]:
    return target_feedback(body, session, None)
