"""Physical request audit and reservations; llm_usage remains the known-spend ledger."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Numeric, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from unspun.core.db import Base


class BudgetPolicy(Base):
    __tablename__ = "budget_policy"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_budget_singleton"),
        CheckConstraint("scope IN ('production','evaluation')", name="ck_budget_scope"),
        CheckConstraint("monthly_limit_usd BETWEEN 0 AND 50", name="ck_budget_limit"),
    )
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    scope: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(default=False, server_default="false")
    monthly_limit_usd: Mapped[Decimal] = mapped_column(Numeric(24, 12))
    stage_caps: Mapped[dict[str, Any]] = mapped_column(JSONB)
    version: Mapped[str] = mapped_column(Text)
    coverage_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    incident: Mapped[str | None] = mapped_column(Text)
    provider_limit_usd: Mapped[Decimal | None] = mapped_column(Numeric(24, 12))
    provider_usage_usd: Mapped[Decimal | None] = mapped_column(Numeric(24, 12))
    provider_limit_kind: Mapped[str | None] = mapped_column(Text)
    key_fingerprint: Mapped[str | None] = mapped_column(Text)
    provider_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BudgetCarry(Base):
    __tablename__ = "budget_carry"
    __table_args__ = (CheckConstraint("amount_usd >= 0", name="ck_budget_carry_amount"),)
    month: Mapped[date] = mapped_column(Date, primary_key=True)
    amount_usd: Mapped[Decimal] = mapped_column(Numeric(24, 12))
    provider_monthly_usd: Mapped[Decimal | None] = mapped_column(Numeric(24, 12))
    ledger_at_observation_usd: Mapped[Decimal] = mapped_column(Numeric(24, 12))
    basis: Mapped[str] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BilledRequest(Base):
    __tablename__ = "billed_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('reserved','usage_unknown','responded','settled_without_result')",
            name="ck_billed_request_status",
        ),
        CheckConstraint("reserved_usd >= 0", name="ck_billed_request_reserved"),
        Index("ix_billed_requests_status", "status"),
        Index("ix_billed_requests_object", "object_key", "status"),
        Index("ix_billed_requests_started", "started_at"),
    )
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    logical_key: Mapped[str | None] = mapped_column(Text, unique=True)
    purpose: Mapped[str] = mapped_column(Text)
    stage: Mapped[str] = mapped_column(Text)
    phase: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    request_fingerprint: Mapped[str] = mapped_column(Text)
    price_version: Mapped[str] = mapped_column(Text)
    reserved_usd: Mapped[Decimal] = mapped_column(Numeric(24, 12))
    status: Mapped[str] = mapped_column(Text)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("pipeline_tasks.id"))
    task_attempt_id: Mapped[int | None] = mapped_column(ForeignKey("task_attempts.id"))
    article_id: Mapped[int | None] = mapped_column(ForeignKey("articles.id"), index=True)
    source_id: Mapped[str | None] = mapped_column(Text)
    object_key: Mapped[str | None] = mapped_column(Text)
    usage_id: Mapped[int | None] = mapped_column(ForeignKey("llm_usage.id"), unique=True)
    provider_generation_id: Mapped[str | None] = mapped_column(Text)
    http_status: Mapped[int | None]
    response_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    usage_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    reconciliation: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
