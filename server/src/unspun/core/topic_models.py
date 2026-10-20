"""R2 topic resources and retained revisions, independent of legacy Events and R1 cards."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from unspun.core.db import Base


class Topic(Base):
    __tablename__ = "topics"
    __table_args__ = (
        CheckConstraint("kind IN ('event','issue')", name="ck_topic_kind"),
        CheckConstraint("status IN ('active','archived')", name="ck_topic_status"),
        CheckConstraint("revision >= 0", name="ck_topic_revision"),
        CheckConstraint("jsonb_typeof(domains)='array'", name="ck_topic_domains"),
    )
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    domains: Mapped[list[str]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column()
    definition_revision: Mapped[int] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TopicChange(Base):
    __tablename__ = "topic_changes"
    __table_args__ = (
        ForeignKeyConstraint(["topic_id"], ["topics.id"]),
        UniqueConstraint("topic_id", "mutation_id", name="uq_topic_mutation"),
        CheckConstraint("revision > 0", name="ck_topic_change_revision"),
    )
    topic_id: Mapped[str] = mapped_column(Text, primary_key=True)
    revision: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    mutation_id: Mapped[str] = mapped_column(Text)
    request_fingerprint: Mapped[str] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    command: Mapped[dict[str, Any]] = mapped_column(JSONB)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any]] = mapped_column(JSONB)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class TopicMember(Base):
    __tablename__ = "topic_members"
    __table_args__ = (
        ForeignKeyConstraint(
            ["topic_id", "revision"], ["topic_changes.topic_id", "topic_changes.revision"]
        ),
        ForeignKeyConstraint(
            ["article_id", "material_id"], ["content_materials.article_id", "content_materials.id"]
        ),
        CheckConstraint(
            "relation IN ('report','background','opinion','explanation','reprint')",
            name="ck_topic_member_relation",
        ),
        CheckConstraint("jsonb_typeof(evidence)='array'", name="ck_topic_member_evidence"),
    )
    topic_id: Mapped[str] = mapped_column(ForeignKey("topics.id"), primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id"), primary_key=True)
    material_id: Mapped[int] = mapped_column()
    revision: Mapped[int] = mapped_column()
    active: Mapped[bool] = mapped_column()
    relation: Mapped[str] = mapped_column(Text)
    basis: Mapped[str] = mapped_column(Text)
    decision_version: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)


class TopicUpdate(Base):
    """Append-only revisions; a retraction retains its predecessor and evidence."""

    __tablename__ = "topic_updates"
    __table_args__ = (
        ForeignKeyConstraint(
            ["topic_id", "revision"], ["topic_changes.topic_id", "topic_changes.revision"]
        ),
        ForeignKeyConstraint(
            ["topic_id", "update_id", "supersedes_revision"],
            ["topic_updates.topic_id", "topic_updates.update_id", "topic_updates.revision"],
        ),
        CheckConstraint("status IN ('active','retracted')", name="ck_topic_update_status"),
        CheckConstraint(
            "supersedes_revision IS NULL OR supersedes_revision < revision",
            name="ck_topic_update_predecessor",
        ),
    )
    topic_id: Mapped[str] = mapped_column(ForeignKey("topics.id"), primary_key=True)
    update_id: Mapped[str] = mapped_column(Text, primary_key=True)
    revision: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    supersedes_revision: Mapped[int | None]
    status: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    input_fingerprint: Mapped[str] = mapped_column(Text)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class TopicDerivation(Base):
    """Stored drafts are structural evidence, never a claim of semantic/public approval."""

    __tablename__ = "topic_derivations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["topic_id", "revision"], ["topic_changes.topic_id", "topic_changes.revision"]
        ),
        ForeignKeyConstraint(
            ["topic_id", "kind", "supersedes_revision"],
            ["topic_derivations.topic_id", "topic_derivations.kind", "topic_derivations.revision"],
        ),
        CheckConstraint("kind IN ('overview','guide')", name="ck_topic_derivation_kind"),
        CheckConstraint("status='draft'", name="ck_topic_derivation_draft"),
        CheckConstraint(
            "supersedes_revision IS NULL OR supersedes_revision < revision",
            name="ck_topic_derivation_predecessor",
        ),
    )
    topic_id: Mapped[str] = mapped_column(ForeignKey("topics.id"), primary_key=True)
    kind: Mapped[str] = mapped_column(Text, primary_key=True)
    revision: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    supersedes_revision: Mapped[int | None]
    status: Mapped[str] = mapped_column(Text, default="draft", server_default="draft")
    input_fingerprint: Mapped[str] = mapped_column(Text)
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    contract: Mapped[dict[str, Any]] = mapped_column(JSONB)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
