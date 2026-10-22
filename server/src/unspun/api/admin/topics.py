"""Authenticated manual topic corrections and read-only member task receipts."""

from collections.abc import Generator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field, StringConstraints
from sqlalchemy import Numeric, cast, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from unspun.api.admin.auth import require_admin_identity
from unspun.api.admin.expenses import same_origin
from unspun.api.events import get_db
from unspun.core.billing_models import BilledRequest
from unspun.core.config import get_settings
from unspun.core.content import ContentContract
from unspun.core.db import session_scope
from unspun.core.member_models import MemberJudgment
from unspun.core.models import Article, ContentMaterial, LlmUsage
from unspun.core.sources import load_sources
from unspun.core.task_models import PipelineTask, TaskAttempt
from unspun.core.topic_contracts import (
    DefineTopic,
    DerivationContract,
    EvidenceRef,
    Nonblank,
    RemoveMember,
    SetMember,
    TopicMutation,
)
from unspun.core.topic_models import Topic, TopicChange, TopicDerivation, TopicMember, TopicUpdate
from unspun.core.topics import (
    TopicConflict,
    canonical_content_id,
    member_input_snapshot,
    mutate_topic,
    validate_member,
    validate_version,
)

router = APIRouter()
Db = Annotated[Session, Depends(get_db)]
Actor = Annotated[str, Depends(require_admin_identity)]
Write = Annotated[None, Depends(same_origin)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Relation = Literal["report", "background", "opinion", "explanation", "reprint"]
MEMBER_KINDS = ("topic_recall", "topic_judge", "topic_review")
MANUAL_VERSION = "r2-member-manual-v1"
DETAIL_PAGE_SIZE = 25
RECORD_LIMIT = 100


def get_write_db() -> Generator[Session]:
    # GET's dependency uses a read-only snapshot. Writes own a separate transaction.
    with session_scope() as session:
        yield session


WriteDb = Annotated[Session, Depends(get_write_db)]


class CreateTopic(ContentContract):
    topic_id: UUID
    mutation_id: UUID
    reason: Reason
    kind: Literal["event", "issue"]
    title: Nonblank
    domains: tuple[str, ...] = Field(min_length=1, max_length=3)


class Correction(ContentContract):
    mutation_id: UUID
    expected_revision: int = Field(ge=1, le=2147483646)
    reason: Reason


class CorrectMember(Correction):
    article_id: int = Field(gt=0)
    material_id: int = Field(gt=0)
    relation: Relation
    basis: Nonblank
    evidence: tuple[EvidenceRef, ...] = Field(min_length=1, max_length=20)


def _topic(row: Topic) -> dict[str, Any]:
    return {
        name: getattr(row, name)
        for name in (
            "id",
            "kind",
            "title",
            "domains",
            "status",
            "revision",
            "definition_revision",
            "created_at",
            "updated_at",
        )
    }


def _task(row: PipelineTask) -> dict[str, Any]:
    return {
        name: getattr(row, name)
        for name in (
            "id",
            "kind",
            "status",
            "article_id",
            "source_id",
            "object_key",
            "strategy_version",
            "attempts",
            "failures",
            "last_error",
            "result",
            "created_at",
            "finished_at",
            "lease_until",
        )
    }


def _mutate(session: Session, topic_id: UUID, command: TopicMutation) -> dict[str, Any]:
    try:
        receipt = mutate_topic(
            session, topic_id, command, sources=load_sources(), now=datetime.now(UTC)
        )
    except TopicConflict as error:
        raise HTTPException(409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(422, detail=str(error)) from error
    return {
        "topic_id": receipt.topic_id,
        "revision": receipt.revision,
        "mutation_id": receipt.mutation_id,
    }


@router.get("/topics")
def list_topics(
    session: Db,
    q: str | None = Query(default=None, max_length=200),
    status: Literal["active", "archived"] | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=50),
) -> dict[str, Any]:
    conditions: list[ColumnElement[bool]] = []
    if q and q.strip():
        conditions.append(Topic.title.icontains(q.strip(), autoescape=True))
    if status:
        conditions.append(Topic.status == status)
    total = session.scalar(select(func.count()).select_from(Topic).where(*conditions)) or 0
    members = (
        select(func.count())
        .select_from(TopicMember)
        .where(TopicMember.topic_id == Topic.id, TopicMember.active.is_(True))
        .correlate(Topic)
        .scalar_subquery()
    )
    rows = session.execute(
        select(Topic, members)
        .where(*conditions)
        .order_by(Topic.updated_at.desc(), Topic.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return {
        "items": [{**_topic(row), "active_member_count": count} for row, count in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "processing_enabled": get_settings().r2_member_processing_enabled,
    }


@router.post("/topics", status_code=201)
def create_topic(body: CreateTopic, _: Write, session: WriteDb, actor: Actor) -> dict[str, Any]:
    try:
        change = DefineTopic(kind=body.kind, title=body.title, domains=body.domains)
    except ValueError as error:
        raise HTTPException(422, detail=str(error)) from error
    return _mutate(
        session,
        body.topic_id,
        TopicMutation(
            mutation_id=body.mutation_id,
            expected_revision=0,
            actor=actor,
            reason=body.reason,
            change=change,
        ),
    )


@router.get("/topics/{topic_id}")
def topic_detail(
    topic_id: UUID,
    session: Db,
    member_page: int = Query(default=1, ge=1),
    history_page: int = Query(default=1, ge=1),
) -> dict[str, Any]:
    topic = session.get(Topic, str(topic_id))
    if topic is None:
        raise HTTPException(404, "Topic not found")
    sources, now = load_sources(), datetime.now(UTC)
    members_total = (
        session.scalar(
            select(func.count()).select_from(TopicMember).where(TopicMember.topic_id == topic.id)
        )
        or 0
    )
    rows = session.execute(
        select(TopicMember, Article, ContentMaterial)
        .join(Article, Article.id == TopicMember.article_id)
        .join(ContentMaterial, ContentMaterial.id == TopicMember.material_id)
        .where(TopicMember.topic_id == topic.id)
        .order_by(TopicMember.article_id)
        .offset((member_page - 1) * DETAIL_PAGE_SIZE)
        .limit(DETAIL_PAGE_SIZE)
    )
    members = [
        {
            "article_id": member.article_id,
            "title": article.title,
            "url": article.url,
            "source_id": article.source_id,
            "material_id": member.material_id,
            "scope": material.scope,
            "active": member.active,
            "relation": member.relation,
            "basis": member.basis,
            "decision_version": member.decision_version,
            "evidence": member.evidence,
            "check": validate_member(session, member, sources, now).model_dump(mode="json"),
        }
        for member, article, material in rows
    ]
    changes_total = (
        session.scalar(
            select(func.count()).select_from(TopicChange).where(TopicChange.topic_id == topic.id)
        )
        or 0
    )
    changes = list(
        session.scalars(
            select(TopicChange)
            .where(TopicChange.topic_id == topic.id)
            .order_by(TopicChange.revision.desc())
            .offset((history_page - 1) * DETAIL_PAGE_SIZE)
            .limit(DETAIL_PAGE_SIZE)
        )
    )
    updates_total = (
        session.scalar(
            select(func.count()).select_from(TopicUpdate).where(TopicUpdate.topic_id == topic.id)
        )
        or 0
    )
    updates = list(
        session.scalars(
            select(TopicUpdate)
            .where(TopicUpdate.topic_id == topic.id)
            .order_by(TopicUpdate.revision.desc())
            .limit(RECORD_LIMIT)
        )
    )
    derivations_total = (
        session.scalar(
            select(func.count())
            .select_from(TopicDerivation)
            .where(TopicDerivation.topic_id == topic.id)
        )
        or 0
    )
    derivations: list[dict[str, Any]] = []
    for row in session.scalars(
        select(TopicDerivation)
        .where(TopicDerivation.topic_id == topic.id)
        .order_by(TopicDerivation.revision.desc())
        .limit(RECORD_LIMIT)
    ):
        try:
            contract = DerivationContract.model_validate(row.contract)
            check = validate_version(
                session, row, sources=sources, now=now, contract=contract
            ).model_dump(mode="json")
        except ValueError:
            check = {"valid": False, "reasons": ["invalid_stored_contract"]}
        derivations.append(
            {
                "kind": row.kind,
                "revision": row.revision,
                "status": row.status,
                "payload": row.payload,
                "contract": row.contract,
                "check": check,
                "contract_verification": "stored_contract_only",
            }
        )

    def changed_fields(value: dict[str, Any] | None) -> dict[str, Any] | None:
        # Preserve the complete edited fields; the qualification snapshot is not an edit.
        return {k: v for k, v in value.items() if k != "input_snapshot"} if value else value

    return {
        "topic": _topic(topic),
        "members": members,
        "members_total": members_total,
        "member_page": member_page,
        "page_size": DETAIL_PAGE_SIZE,
        "changes": [
            {
                "revision": row.revision,
                "mutation_id": row.mutation_id,
                "actor": row.actor,
                "reason": row.reason,
                "command": row.command,
                "before": changed_fields(row.before),
                "after": changed_fields(row.after),
                "recorded_at": row.recorded_at,
            }
            for row in changes
        ],
        "changes_total": changes_total,
        "history_page": history_page,
        "updates": [
            {
                "update_id": row.update_id,
                "revision": row.revision,
                "status": row.status,
                "payload": row.payload,
                "check": validate_version(session, row, sources=sources, now=now).model_dump(
                    mode="json"
                ),
            }
            for row in updates
        ],
        "updates_total": updates_total,
        "derivations": derivations,
        "derivations_total": derivations_total,
        "version_record_limit": RECORD_LIMIT,
    }


@router.get("/member-contents/{article_id}")
def member_content(article_id: int, session: Db) -> dict[str, Any]:
    if session.get(Article, article_id) is None:
        raise HTTPException(404, "Content not found")
    try:
        root = canonical_content_id(session, article_id)
        article = session.get(Article, root)
        if article is None or article.current_material_id is None:
            raise ValueError("content has no current material")
        member_input_snapshot(
            session, root, article.current_material_id, load_sources(), datetime.now(UTC)
        )
    except ValueError as error:
        raise HTTPException(422, detail=str(error)) from error
    material = session.get(ContentMaterial, article.current_material_id)
    assert material is not None
    required_voice = {"question_background": "question", "media_description": "description"}.get(
        material.scope
    )
    return {
        "article_id": root,
        "requested_article_id": article_id,
        "title": article.title,
        "url": article.url,
        "source_id": article.source_id,
        "material_id": material.id,
        "scope": material.scope,
        "paragraphs": [
            {
                "index": i,
                "text": paragraph.get("text", ""),
                "voice": required_voice,
                "allowed_voices": [required_voice]
                if required_voice
                else ["reported", "author", "question", "description"],
            }
            for i, paragraph in enumerate(material.paragraphs)
        ],
    }


@router.post("/topics/{topic_id}/members")
def correct_member(
    topic_id: UUID, body: CorrectMember, _: Write, session: WriteDb, actor: Actor
) -> dict[str, Any]:
    return _mutate(
        session,
        topic_id,
        TopicMutation(
            mutation_id=body.mutation_id,
            expected_revision=body.expected_revision,
            actor=actor,
            reason=body.reason,
            change=SetMember(
                article_id=body.article_id,
                material_id=body.material_id,
                relation=body.relation,
                basis=body.basis,
                evidence=body.evidence,
                decision_version=MANUAL_VERSION,
            ),
        ),
    )


@router.post("/topics/{topic_id}/members/{article_id}/remove")
def remove_member(
    topic_id: UUID, article_id: int, body: Correction, _: Write, session: WriteDb, actor: Actor
) -> dict[str, Any]:
    if article_id <= 0:
        raise HTTPException(422, "Invalid member content ID")
    return _mutate(
        session,
        topic_id,
        TopicMutation(
            mutation_id=body.mutation_id,
            expected_revision=body.expected_revision,
            actor=actor,
            reason=body.reason,
            change=RemoveMember(article_id=article_id),
        ),
    )


@router.get("/member-tasks")
def member_tasks(
    session: Db,
    topic_id: UUID | None = None,
    article_id: int | None = Query(default=None, gt=0),
    status: str | None = Query(default=None, max_length=40),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=50),
) -> dict[str, Any]:
    conditions: list[ColumnElement[bool]] = [PipelineTask.kind.in_(MEMBER_KINDS)]
    if article_id:
        conditions.append(PipelineTask.article_id == article_id)
    if status:
        conditions.append(PipelineTask.status == status)
    if topic_id:
        conditions.append(
            or_(
                PipelineTask.payload["candidate"]["topic"]["id"].astext == str(topic_id),
                PipelineTask.payload["topics"].contains([{"id": str(topic_id)}]),
                PipelineTask.id.in_(
                    select(MemberJudgment.task_id).where(MemberJudgment.topic_id == str(topic_id))
                ),
            )
        )
    total = session.scalar(select(func.count()).select_from(PipelineTask).where(*conditions)) or 0
    rows = session.scalars(
        select(PipelineTask)
        .where(*conditions)
        .order_by(PipelineTask.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return {
        "items": [_task(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/member-tasks/{task_id}")
def member_task_detail(task_id: int, session: Db) -> dict[str, Any]:
    task = session.get(PipelineTask, task_id)
    if task is None or task.kind not in MEMBER_KINDS:
        raise HTTPException(404, "Member task not found")
    attempts_total = (
        session.scalar(
            select(func.count()).select_from(TaskAttempt).where(TaskAttempt.task_id == task.id)
        )
        or 0
    )
    attempts = list(
        session.scalars(
            select(TaskAttempt)
            .where(TaskAttempt.task_id == task.id)
            .order_by(TaskAttempt.id.desc())
            .limit(RECORD_LIMIT)
        )
    )
    conditions = [MemberJudgment.task_id == task.id]
    decision_key = task.payload.get("decision_key")
    if isinstance(decision_key, str):
        conditions.append(MemberJudgment.input_fingerprint == decision_key)
    judgments_total = (
        session.scalar(select(func.count()).select_from(MemberJudgment).where(or_(*conditions)))
        or 0
    )
    judgments = list(
        session.scalars(
            select(MemberJudgment)
            .where(or_(*conditions))
            .order_by(MemberJudgment.created_at.desc())
            .limit(RECORD_LIMIT)
        )
    )
    calls_total = (
        session.scalar(
            select(func.count()).select_from(BilledRequest).where(BilledRequest.task_id == task.id)
        )
        or 0
    )
    known = session.scalar(
        select(func.sum(cast(LlmUsage.cost_usd, Numeric(24, 12))))
        .select_from(BilledRequest)
        .join(LlmUsage, LlmUsage.id == BilledRequest.usage_id)
        .where(BilledRequest.task_id == task.id)
    ) or Decimal(0)
    held, unresolved = session.execute(
        select(func.sum(BilledRequest.reserved_usd), func.count()).where(
            BilledRequest.task_id == task.id,
            BilledRequest.status.in_(("reserved", "usage_unknown")),
        )
    ).one()
    calls = session.execute(
        select(BilledRequest, LlmUsage.cost_usd)
        .outerjoin(LlmUsage, LlmUsage.id == BilledRequest.usage_id)
        .where(BilledRequest.task_id == task.id)
        .order_by(BilledRequest.started_at.desc(), BilledRequest.id)
        .limit(RECORD_LIMIT)
    )
    return {
        "task": _task(task),
        "attempts_total": attempts_total,
        "attempts": [
            {
                name: getattr(row, name)
                for name in (
                    "id",
                    "claim_version",
                    "status",
                    "worker",
                    "started_at",
                    "ended_at",
                    "error",
                )
            }
            for row in attempts
        ],
        "judgments_total": judgments_total,
        "judgments": [
            {
                name: getattr(row, name)
                for name in (
                    "input_fingerprint",
                    "task_id",
                    "article_id",
                    "topic_id",
                    "topic_revision",
                    "decision",
                    "review",
                    "status",
                    "applied_revision",
                    "created_at",
                    "input_snapshot",
                )
            }
            for row in judgments
        ],
        "calls_total": calls_total,
        "calls": [
            {
                **{
                    name: getattr(row, name)
                    for name in (
                        "id",
                        "stage",
                        "phase",
                        "status",
                        "model",
                        "task_id",
                        "task_attempt_id",
                        "provider_generation_id",
                        "http_status",
                        "error",
                        "started_at",
                        "ended_at",
                    )
                },
                "known_cost_usd": str(cost) if row.usage_id is not None else None,
                "reserved_usd": str(row.reserved_usd)
                if row.status in {"reserved", "usage_unknown"}
                else None,
            }
            for row, cost in calls
        ],
        "costs": {
            "known_usd": str(known),
            "held_usd": str(held or Decimal(0)),
            "unknown_requests": unresolved,
            "physical_requests": calls_total,
        },
        "record_limit": RECORD_LIMIT,
    }
