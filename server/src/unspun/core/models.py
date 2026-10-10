"""ORM models for the M1 pipeline: articles, events, and run-report logs.

Sources are configured in config/sources.yml, not in the database, so
`Article.source_id` is a plain string referencing a config entry.
"""

from datetime import date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Date, DateTime, ForeignKey, Index, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from unspun.core.db import Base

# Embedding column width is part of the schema; changing it requires a
# migration. Qwen3-Embedding supports MRL truncation to this size, and it
# stays well under pgvector's 2000-dim index limit.
EMBEDDING_DIM = 1024


class Event(Base):
    """A cluster of articles about the same real-world story."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str | None] = mapped_column(Text)
    summary_zh: Mapped[str | None] = mapped_column(Text)
    centroid: Mapped[Any | None] = mapped_column(Vector(EMBEDDING_DIM))
    score_final: Mapped[float | None]
    # Score components, LLM reason, and confidence; shape is owned by the
    # scoring module so it can evolve without migrations.
    score_breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Bumped whenever an article joins or content changes; scored_at older
    # than this means the event needs (re)scoring.
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    articles: Mapped[list["Article"]] = relationship(back_populates="event")
    viewpoint: Mapped["EventViewpoint | None"] = relationship(
        back_populates="event", cascade="all, delete-orphan", passive_deletes=True
    )


class Article(Base):
    """One fetched item from a configured source."""

    __tablename__ = "articles"
    __table_args__ = (Index("ix_articles_source_id", "source_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text, unique=True)
    title: Mapped[str] = mapped_column(Text)
    lang: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    content: Mapped[str | None] = mapped_column(Text)
    title_zh: Mapped[str | None] = mapped_column(Text)
    summary_zh: Mapped[str | None] = mapped_column(Text)
    # Summarize failures so far; articles at pipeline.max_summary_failures
    # (config/scoring.yml) are skipped, otherwise a permanently broken
    # article burns a batch slot every cycle.
    summary_failures: Mapped[int] = mapped_column(default=0, server_default="0")
    embedding: Mapped[Any | None] = mapped_column(Vector(EMBEDDING_DIM))
    event_id: Mapped[int | None] = mapped_column(ForeignKey("events.id"), index=True)

    event: Mapped[Event | None] = relationship(back_populates="articles")


class EventViewpoint(Base):
    """LLM-generated viewpoint comparison for one event (at most one row each).

    Regeneration replaces the whole row. The payload shape (per-source claims
    and disagreement points) is owned by the viewpoints pipeline stage so it
    can evolve without migrations.
    """

    __tablename__ = "event_viewpoints"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), unique=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # Hash of the event's sorted article ids; unchanged fingerprint means the
    # inputs did not change and no regeneration is needed.
    input_fingerprint: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    event: Mapped[Event] = relationship(back_populates="viewpoint")


class Digest(Base):
    """Daily digest for one report date; same-day regeneration replaces the row.

    The payload shape (intro paragraph and selected events) is owned by the
    digest pipeline stage so it can evolve without migrations.
    """

    __tablename__ = "digests"
    __table_args__ = (UniqueConstraint("report_date", "kind", name="uq_digests_report_date_kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    report_date: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(Text, default="daily", server_default="daily")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class FetchLog(Base):
    """Per-source outcome of one fetch run; feeds the daily run report."""

    __tablename__ = "fetch_logs"
    __table_args__ = (Index("ix_fetch_logs_run_at", "run_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    source_id: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)  # ok | error
    error: Mapped[str | None] = mapped_column(Text)
    new_articles: Mapped[int] = mapped_column(default=0)


class PipelineRun(Base):
    """Per-stage processed counts of one worker AI cycle; feeds the run report."""

    __tablename__ = "pipeline_runs"
    __table_args__ = (Index("ix_pipeline_runs_run_at", "run_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    summarized: Mapped[int] = mapped_column(default=0)
    embedded: Mapped[int] = mapped_column(default=0)
    clustered: Mapped[int] = mapped_column(default=0)
    new_events: Mapped[int] = mapped_column(default=0)
    scored: Mapped[int] = mapped_column(default=0)


class LlmUsage(Base):
    """One LLM/embedding API call; feeds the daily cost report."""

    __tablename__ = "llm_usage"
    __table_args__ = (Index("ix_llm_usage_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    purpose: Mapped[str] = mapped_column(Text)  # summary | importance | embedding
    model: Mapped[str] = mapped_column(Text)
    prompt_tokens: Mapped[int] = mapped_column(default=0)
    completion_tokens: Mapped[int] = mapped_column(default=0)
    cost_usd: Mapped[float] = mapped_column(default=0.0)
