"""Retained generation and semantic audit evidence, separate from structural topic drafts."""

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from unspun.core.db import Base


class TopicSynthesis(Base):
    __tablename__ = "topic_syntheses"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','abstained','rejected','stale','applied')",
            name="ck_topic_synthesis_status",
        ),
        CheckConstraint("response_mode IN ('live','mock')", name="ck_topic_synthesis_mode"),
    )
    input_fingerprint: Mapped[str] = mapped_column(Text, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("pipeline_tasks.id"), unique=True)
    topic_id: Mapped[str] = mapped_column(ForeignKey("topics.id"), index=True)
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    draft: Mapped[dict[str, Any]] = mapped_column(JSONB)
    generation_receipt: Mapped[dict[str, Any]] = mapped_column(JSONB)
    review: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    review_receipt: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    response_mode: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    applied: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
