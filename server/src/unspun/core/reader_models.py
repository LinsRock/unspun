"""Single-user R1 preferences, stable interest resources, and reversible feedback."""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from unspun.core.db import Base


class ReaderState(Base):
    __tablename__ = "reader_state"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_reader_singleton"),
        CheckConstraint("version >= 0", name="ck_reader_version"),
        CheckConstraint("sort IN ('recommended','latest')", name="ck_reader_sort"),
    )
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    version: Mapped[int] = mapped_column(default=0, server_default="0")
    sort: Mapped[str] = mapped_column(Text, default="recommended", server_default="recommended")
    last_mutation_id: Mapped[str | None] = mapped_column(Text)
    last_mutation_fingerprint: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReaderInterest(Base):
    __tablename__ = "reader_interests"
    __table_args__ = (
        CheckConstraint("kind IN ('domain','term','source','author')", name="ck_interest_kind"),
    )
    resource_key: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str] = mapped_column(Text)
    target: Mapped[dict[str, Any]] = mapped_column(JSONB)
    label: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContentFeedback(Base):
    __tablename__ = "content_feedback"
    __table_args__ = (
        CheckConstraint(
            "value IN ('interested','not_interested')", name="ck_content_feedback_value"
        ),
    )
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id"), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReaderChange(Base):
    """Retain feedback/interest changes and revocations, including empty states."""

    __tablename__ = "reader_changes"
    version: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    mutation_id: Mapped[str] = mapped_column(Text, unique=True)
    fingerprint: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    target: Mapped[dict[str, Any]] = mapped_column(JSONB)
    value: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReaderRequest(Base):
    """Receipts include successful no-ops without inventing a preference revision."""

    __tablename__ = "reader_requests"
    __table_args__ = (CheckConstraint("version >= 0", name="ck_reader_request_version"),)
    mutation_id: Mapped[str] = mapped_column(Text, primary_key=True)
    fingerprint: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column()
    unchanged: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TopicPreference(Base):
    """Explicit stable topic targets; never inferred from terms or member feedback."""

    __tablename__ = "topic_preferences"
    __table_args__ = (
        CheckConstraint(
            "feedback IN ('interested','not_interested')", name="ck_topic_preference_feedback"
        ),
        CheckConstraint("followed OR feedback IS NOT NULL", name="ck_topic_preference_active"),
        CheckConstraint("version > 0", name="ck_topic_preference_version"),
    )
    topic_id: Mapped[str] = mapped_column(ForeignKey("topics.id"), primary_key=True)
    followed: Mapped[bool] = mapped_column(Boolean)
    feedback: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
