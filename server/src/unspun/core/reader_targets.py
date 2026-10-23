"""Typed explicit targets and topic-only preference changes under the reader lock."""

from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from unspun.core.config import get_settings
from unspun.core.reader_models import TopicPreference
from unspun.core.sources import load_sources
from unspun.core.topic_synthesis import qualified_topic_text


class ContentTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["content"]
    id: int = Field(gt=0, lt=2**63, strict=True)


class TopicTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["topic"]
    id: UUID


FeedbackTarget = Annotated[ContentTarget | TopicTarget, Field(discriminator="type")]


def require_topic_preferences() -> None:
    if not get_settings().r2_topic_preferences_enabled:
        raise HTTPException(404, "Topic preferences are disabled")


def topic_preferences(session: Session) -> list[dict[str, Any]]:
    return [
        {
            "target": {"type": "topic", "id": row.topic_id},
            "followed": row.followed,
            "feedback": row.feedback,
            "version": row.version,
        }
        for row in session.scalars(select(TopicPreference).order_by(TopicPreference.topic_id))
    ]


def change_topic_preference(
    session: Session,
    kind: str,
    target: dict[str, Any],
    value: dict[str, Any] | None,
    version: int,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    require_topic_preferences()
    parsed = TopicTarget.model_validate(target)
    identity = str(parsed.id)
    # Revocation and historical replays never depend on current publication.
    if (
        value is not None
        and qualified_topic_text(session, parsed.id, sources=load_sources(), now=datetime.now(UTC))
        is None
    ):
        raise HTTPException(404, "Current reviewed topic is not published")
    row = session.get(TopicPreference, identity)
    before = {"followed": row.followed, "feedback": row.feedback} if row else None
    after: dict[str, Any] | None = dict(before or {"followed": False, "feedback": None})
    if kind == "topic_follow":
        after["followed"] = value is not None
    else:
        after["feedback"] = value["value"] if value else None
    after = after if after["followed"] or after["feedback"] else None
    if before != after:
        if after:
            if row is None:
                if (session.scalar(select(func.count()).select_from(TopicPreference)) or 0) >= 256:
                    raise HTTPException(422, "At most 256 active topic preferences are supported")
                row = TopicPreference(topic_id=identity)
                session.add(row)
            row.followed, row.feedback = after["followed"], after["feedback"]
            row.version, row.updated_at = version, datetime.now(UTC)
        elif row:
            session.delete(row)
    return before, after
