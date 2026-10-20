"""Versioned vectors and retained member decisions; no legacy vector adoption."""

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from unspun.core.db import Base


class ContentVector(Base):
    __tablename__ = "content_vectors"
    __table_args__ = (
        ForeignKeyConstraint(
            ["article_id", "material_id"], ["content_materials.article_id", "content_materials.id"]
        ),
        CheckConstraint("dimensions > 0", name="ck_content_vector_dimensions"),
        CheckConstraint(
            "jsonb_typeof(vector)='array' AND jsonb_array_length(vector)=dimensions",
            name="ck_content_vector_size",
        ),
    )
    input_fingerprint: Mapped[str] = mapped_column(Text, primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id"), index=True)
    material_id: Mapped[int]
    model: Mapped[str] = mapped_column(Text)
    dimensions: Mapped[int]
    contract_version: Mapped[str] = mapped_column(Text)
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    vector: Mapped[list[float]] = mapped_column(JSONB)
    call_ids: Mapped[list[str]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MemberJudgment(Base):
    __tablename__ = "member_judgments"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','independent','rejected','stale','applied')",
            name="ck_member_judgment_status",
        ),
    )
    input_fingerprint: Mapped[str] = mapped_column(Text, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("pipeline_tasks.id"))
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id"), index=True)
    topic_id: Mapped[str] = mapped_column(ForeignKey("topics.id"), index=True)
    topic_revision: Mapped[int]
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    decision: Mapped[dict[str, Any]] = mapped_column(JSONB)
    review: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text)
    applied_revision: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
