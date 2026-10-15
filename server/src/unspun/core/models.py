"""ORM models for the M1 pipeline: articles, events, and run-report logs.

Sources are configured in config/sources.yml, not in the database, so
`Article.source_id` is a plain string referencing a config entry.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
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
    public_impact: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
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
    __table_args__ = (
        Index("ix_articles_source_id", "source_id"),
        Index("ix_articles_event_publication", "event_id", "reported_at", "fetched_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text, unique=True)
    title: Mapped[str] = mapped_column(Text)
    lang: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reported_date: Mapped[date | None] = mapped_column(Date)
    reported_precision: Mapped[str] = mapped_column(
        Text, default="unknown", server_default="unknown"
    )
    reported_basis: Mapped[str | None] = mapped_column(Text)
    publisher_group: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    content_basis: Mapped[str] = mapped_column(Text, default="unknown", server_default="unknown")
    content: Mapped[str | None] = mapped_column(Text)
    title_zh: Mapped[str | None] = mapped_column(Text)
    summary_zh: Mapped[str | None] = mapped_column(Text)
    summary_grounding: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
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
    # Hash of sorted source content, metadata, model, and prompts; equality means the
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
    # summary | importance | viewpoint | digest | embedding
    purpose: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    prompt_tokens: Mapped[int] = mapped_column(default=0)
    completion_tokens: Mapped[int] = mapped_column(default=0)
    cost_usd: Mapped[float] = mapped_column(default=0.0)


class ExpenseRule(Base):
    """Current recurring charge terms; existing entries retain their snapshots."""

    __tablename__ = "expense_rules"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_expense_rules_amount"),
        CheckConstraint(
            "cadence IN ('once', 'monthly', 'yearly')", name="ck_expense_rules_cadence"
        ),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_expense_rules_currency"),
        CheckConstraint(
            "once_end IS NULL OR once_end > anchor_date", name="ck_expense_rules_once_end"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(Text)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    currency: Mapped[str] = mapped_column(Text)
    cadence: Mapped[str] = mapped_column(Text)
    anchor_date: Mapped[date] = mapped_column(Date)
    once_end: Mapped[date | None] = mapped_column(Date)
    stop_before: Mapped[date | None] = mapped_column(Date)
    reminder_days: Mapped[int] = mapped_column(default=7, server_default="7")
    version: Mapped[int] = mapped_column(default=1, server_default="1")


class ExpenseEntry(Base):
    """A fixed service charge or prepaid credit, with immutable generation terms."""

    __tablename__ = "expense_entries"
    __table_args__ = (
        UniqueConstraint("rule_id", "period_start", name="uq_expense_entries_rule_period"),
        CheckConstraint("amount > 0", name="ck_expense_entries_amount"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_expense_entries_currency"),
        CheckConstraint("kind IN ('fixed', 'topup')", name="ck_expense_entries_kind"),
        CheckConstraint(
            "status IN ('pending', 'paid', 'canceled')", name="ck_expense_entries_status"
        ),
        CheckConstraint(
            "period_end IS NULL OR period_end > period_start", name="ck_expense_entries_period"
        ),
        CheckConstraint(
            "(paid_on IS NULL OR paid_at IS NULL)", name="ck_expense_entries_payment_precision"
        ),
        CheckConstraint(
            "status != 'paid' OR paid_on IS NOT NULL OR paid_at IS NOT NULL",
            name="ck_expense_entries_paid_date",
        ),
        CheckConstraint(
            "status = 'paid' OR (paid_on IS NULL AND paid_at IS NULL)",
            name="ck_expense_entries_unpaid_date",
        ),
        CheckConstraint(
            "(kind = 'fixed' AND period_start IS NOT NULL AND period_end IS NOT NULL) "
            "OR (kind = 'topup' AND period_start IS NULL AND period_end IS NULL "
            "AND status = 'paid')",
            name="ck_expense_entries_shape",
        ),
        Index("ix_expense_entries_period", "period_start", "period_end"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("expense_rules.id"))
    rule_version: Mapped[int | None]
    name: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(Text)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    currency: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, default="pending", server_default="pending")
    paid_on: Mapped[date | None] = mapped_column(Date)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(default=1, server_default="1")


class FxRate(Base):
    """One original-currency to USD rate effective from a Beijing date."""

    __tablename__ = "fx_rates"
    __table_args__ = (
        UniqueConstraint("currency", "effective_on", name="uq_fx_rates_currency_date"),
        CheckConstraint("rate_to_usd > 0", name="ck_fx_rates_positive"),
        CheckConstraint(
            "currency ~ '^[A-Z]{3}$' AND currency != 'USD'", name="ck_fx_rates_currency"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    currency: Mapped[str] = mapped_column(Text)
    effective_on: Mapped[date] = mapped_column(Date)
    rate_to_usd: Mapped[Decimal] = mapped_column(Numeric(24, 12))
    source: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(default=1, server_default="1")


class ExpenseAudit(Base):
    """Append-only record for every expense write and its stated reason."""

    __tablename__ = "expense_audit"
    id: Mapped[int] = mapped_column(primary_key=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    actor: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    object_type: Mapped[str] = mapped_column(Text)
    object_id: Mapped[int] = mapped_column()
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reason: Mapped[str] = mapped_column(Text)


class FeedPreference(Base):
    __tablename__ = "feed_preferences"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_feed_preferences_singleton"),
        CheckConstraint("version > 0", name="ck_feed_preferences_version"),
        CheckConstraint("sort IN ('newest','hot','important')", name="ck_feed_preferences_sort"),
        CheckConstraint("range IN ('today','24h','7d','all')", name="ck_feed_preferences_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    sort: Mapped[str] = mapped_column(Text)
    range: Mapped[str] = mapped_column(Text)
    version: Mapped[int]
