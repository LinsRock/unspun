"""Persistent R1 work; legacy PipelineRun records keep their original semantics."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from unspun.core.db import Base


class PipelineTask(Base):
    __tablename__ = "pipeline_tasks"
    __table_args__ = (
        CheckConstraint(
            "queue IN ('discovery','material','paid','guide','deadline')", name="ck_task_queue"
        ),
        CheckConstraint(
            "status IN ('pending','running','retry_wait','budget_deferred',"
            "'blocked','completed','failed')",
            name="ck_task_status",
        ),
        CheckConstraint(
            "max_attempts BETWEEN 1 AND 10 AND attempts >= 0 AND failures BETWEEN 0 "
            "AND max_attempts",
            name="ck_task_attempts",
        ),
        CheckConstraint("claim_version >= 0", name="ck_task_version"),
        CheckConstraint("(status = 'running') = (lease_until IS NOT NULL)", name="ck_task_lease"),
        Index("ix_pipeline_tasks_due", "queue", "status", "due_at", "priority", "id"),
        Index("ix_pipeline_tasks_lease", "status", "lease_until"),
        # Serialize one canonical object across stages, without holding a DB
        # transaction open during network work. Different objects remain independent.
        Index(
            "uq_pipeline_tasks_active_object",
            "object_key",
            unique=True,
            postgresql_where=text("status='running'"),
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    queue: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    object_key: Mapped[str] = mapped_column(Text)
    article_id: Mapped[int | None] = mapped_column(ForeignKey("articles.id"), index=True)
    source_id: Mapped[str | None] = mapped_column(Text)
    input_fingerprint: Mapped[str] = mapped_column(Text)
    strategy_version: Mapped[str] = mapped_column(Text)
    cycle_key: Mapped[str | None] = mapped_column(Text)
    dedupe_key: Mapped[str] = mapped_column(Text, unique=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text, default="pending", server_default="pending")
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    priority: Mapped[int] = mapped_column(default=0, server_default="0")
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    failures: Mapped[int] = mapped_column(default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(default=3, server_default="3")
    claim_version: Mapped[int] = mapped_column(default=0, server_default="0")
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_by: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TaskAttempt(Base):
    __tablename__ = "task_attempts"
    __table_args__ = (
        UniqueConstraint("task_id", "claim_version", name="uq_task_attempt_claim"),
        CheckConstraint(
            "status IN ('running','completed','failed','lease_expired','deferred','blocked')",
            name="ck_attempt_status",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("pipeline_tasks.id"), index=True)
    claim_version: Mapped[int]
    worker: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lease_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)


class SourceState(Base):
    """One owner and durable due time per configured discovery route."""

    __tablename__ = "source_states"
    __table_args__ = (
        CheckConstraint("owner IN ('legacy','r1')", name="ck_source_state_owner"),
        CheckConstraint("period_seconds >= 60", name="ck_source_state_period"),
        CheckConstraint("consecutive_failures >= 0", name="ck_source_state_failures"),
    )
    source_id: Mapped[str] = mapped_column(Text, primary_key=True)
    owner: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(default=False, server_default="false")
    period_seconds: Mapped[int]
    schedule_version: Mapped[str] = mapped_column(Text)
    next_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consecutive_failures: Mapped[int] = mapped_column(default=0, server_default="0")
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_new_item_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_item_count: Mapped[int | None]


class DiscoveryBatch(Base):
    """R2 opt-in receipts; historical discovery totals remain unavailable."""

    __tablename__ = "discovery_batches"
    __table_args__ = (UniqueConstraint("source_id", "cycle_key", name="uq_discovery_batch"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[str] = mapped_column(Text, index=True)
    cycle_key: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    quotas: Mapped[dict[str, Any]] = mapped_column(JSONB)
    counters: Mapped[dict[str, Any]] = mapped_column(JSONB)
    material_tasks: Mapped[list[int]] = mapped_column(JSONB)
    paid_outcomes: Mapped[dict[str, Any]] = mapped_column(JSONB)
