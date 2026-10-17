"""Read-only R1 candidate stages and durable task attempts, beside legacy history."""

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from unspun.core.billing_models import BilledRequest
from unspun.core.db import session_scope
from unspun.core.models import (
    Article,
    ContentDerivation,
    ContentMaterial,
    ContentObservation,
    LlmUsage,
)
from unspun.core.sources import load_sources
from unspun.core.task_models import PipelineTask, SourceState, TaskAttempt

router = APIRouter(prefix="/r1")


@router.get("/tasks")
def tasks(
    queue: Literal["discovery", "material", "paid", "guide", "deadline"] | None = None,
    status: str | None = Query(default=None, max_length=40),
    article_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> dict[str, Any]:
    with session_scope() as session:
        query = select(PipelineTask)
        if queue:
            query = query.where(PipelineTask.queue == queue)
        if status:
            query = query.where(PipelineTask.status == status)
        if article_id:
            query = query.where(PipelineTask.article_id == article_id)
        rows = list(session.scalars(query.order_by(PipelineTask.id.desc()).limit(limit)))
        recent_attempts = (
            select(
                TaskAttempt.id,
                func.row_number()
                .over(partition_by=TaskAttempt.task_id, order_by=TaskAttempt.id.desc())
                .label("position"),
            )
            .where(TaskAttempt.task_id.in_([r.id for r in rows]))
            .subquery()
        )
        attempts = (
            list(
                session.scalars(
                    select(TaskAttempt)
                    .join(recent_attempts, recent_attempts.c.id == TaskAttempt.id)
                    .where(recent_attempts.c.position <= 5)
                    .order_by(TaskAttempt.id)
                )
            )
            if rows
            else []
        )
        return {
            "items": [
                {
                    "id": r.id,
                    "queue": r.queue,
                    "kind": r.kind,
                    "status": r.status,
                    "article_id": r.article_id,
                    "source_id": r.source_id,
                    "object_key": r.object_key,
                    "input_fingerprint": r.input_fingerprint,
                    "strategy_version": r.strategy_version,
                    "attempts": r.attempts,
                    "failures": r.failures,
                    "due_at": r.due_at,
                    "lease_until": r.lease_until,
                    "last_error": r.last_error,
                    "result": r.result,
                    "attempt_record_limit": 5,
                    "attempt_records": [
                        {
                            "id": a.id,
                            "claim_version": a.claim_version,
                            "status": a.status,
                            "started_at": a.started_at,
                            "ended_at": a.ended_at,
                            "error": a.error,
                        }
                        for a in attempts
                        if a.task_id == r.id
                    ],
                }
                for r in rows
            ]
        }


@router.get("/contents")
def contents(
    source_id: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=100),
) -> dict[str, Any]:
    with session_scope() as session:
        query = select(Article).where(Article.processing_track == "r1")
        if source_id:
            query = query.where(Article.source_id == source_id)
        rows = list(session.scalars(query.order_by(Article.id.desc()).limit(limit)))
        latest = (
            select(
                ContentDerivation.id,
                func.row_number()
                .over(
                    partition_by=(ContentDerivation.article_id, ContentDerivation.kind),
                    order_by=ContentDerivation.id.desc(),
                )
                .label("position"),
            )
            .where(ContentDerivation.article_id.in_([r.id for r in rows]))
            .subquery()
        )
        versions = (
            list(
                session.scalars(
                    select(ContentDerivation)
                    .join(latest, latest.c.id == ContentDerivation.id)
                    .where(latest.c.position == 1)
                    .order_by(ContentDerivation.id.desc())
                )
            )
            if rows
            else []
        )
        return {
            "items": [
                {
                    "id": r.id,
                    "title": r.title,
                    "source_id": r.source_id,
                    "canonical_content_id": r.canonical_content_id,
                    "current_material_id": r.current_material_id,
                    "metadata_fingerprint": r.metadata_fingerprint,
                    "metadata": r.r1_metadata,
                    "derivation_scope": "latest_per_kind",
                    "derivations": [
                        {
                            "id": v.id,
                            "kind": v.kind,
                            "status": v.status,
                            "reason": v.reason,
                            "material_id": v.material_id,
                            "input_fingerprint": v.input_fingerprint,
                            "contract_version": v.contract_version,
                            "generation_model": v.generation_model,
                            "review_contract": v.review_contract,
                            "review_model": v.review_model,
                            "review_evidence": v.review_evidence,
                            "created_at": v.created_at,
                            "updated_at": v.updated_at,
                        }
                        for v in versions
                        if v.article_id == r.id
                    ],
                }
                for r in rows
            ]
        }


@router.get("/contents/{article_id}")
def content_details(article_id: int) -> dict[str, Any]:
    with session_scope() as session:
        article = session.get(Article, article_id)
        if article is None or article.processing_track != "r1":
            raise HTTPException(404, "R1 content not found")
        materials = list(
            session.scalars(
                select(ContentMaterial)
                .where(ContentMaterial.article_id == article_id)
                .order_by(ContentMaterial.id.desc())
                .limit(20)
            )
        )
        observations = list(
            session.scalars(
                select(ContentObservation)
                .where(ContentObservation.article_id == article_id)
                .order_by(ContentObservation.id.desc())
                .limit(100)
            )
        )
        versions = list(
            session.scalars(
                select(ContentDerivation)
                .where(ContentDerivation.article_id == article_id)
                .order_by(ContentDerivation.id.desc())
                .limit(100)
            )
        )
        calls = list(
            session.execute(
                select(BilledRequest, LlmUsage.cost_usd)
                .outerjoin(LlmUsage, LlmUsage.id == BilledRequest.usage_id)
                .where(BilledRequest.article_id == article_id)
                .order_by(BilledRequest.started_at.desc())
                .limit(100)
            )
        )
        return {
            "calls": [
                {
                    "id": c.id,
                    "stage": c.stage,
                    "phase": c.phase,
                    "status": c.status,
                    "task_id": c.task_id,
                    "known_cost_usd": cost,
                    "reserved_usd": str(c.reserved_usd)
                    if c.status in {"reserved", "usage_unknown"}
                    else None,
                    "error": c.error,
                }
                for c, cost in calls
            ],
            "call_record_limit": 100,
            "id": article.id,
            "title": article.title,
            "url": article.url,
            "metadata": article.r1_metadata,
            "current_material_id": article.current_material_id,
            "canonical_content_id": article.canonical_content_id,
            "materials": [
                {
                    "id": m.id,
                    "scope": m.scope,
                    "access_status": m.access_status,
                    "completeness": m.completeness,
                    "completeness_basis": m.completeness_basis,
                    "input_fingerprint": m.input_fingerprint,
                    "text_fingerprint": m.text_fingerprint,
                    "retrieved_at": m.retrieved_at,
                    "source_url": m.source_url,
                    "response_status": m.response_status,
                    "evidence": m.evidence,
                    "paragraphs": m.paragraphs,
                }
                for m in materials
            ],
            "observations": [
                {
                    "id": o.id,
                    "source_id": o.source_id,
                    "item_key": o.item_key,
                    "observed_at": o.observed_at,
                    "discovered_url": o.discovered_url,
                    "rank": o.rank,
                    "signals": o.signals,
                    "metadata": o.metadata_snapshot,
                }
                for o in observations
            ],
            "derivations": [
                {
                    "id": v.id,
                    "kind": v.kind,
                    "status": v.status,
                    "reason": v.reason,
                    "payload": v.payload,
                    "review_evidence": v.review_evidence,
                    "input_fingerprint": v.input_fingerprint,
                }
                for v in versions
            ],
        }


@router.get("/sources")
def source_states() -> dict[str, Any]:
    with session_scope() as session:
        items: list[dict[str, Any]] = []
        for source in load_sources():
            if source.r1 is None:
                continue
            state = session.get(SourceState, source.id)
            materials = list(
                session.scalars(
                    select(ContentMaterial)
                    .join(Article, Article.id == ContentMaterial.article_id)
                    .where(Article.processing_track == "r1", Article.source_id == source.id)
                    .order_by(ContentMaterial.id.desc())
                    .limit(100)
                )
            )
            failed = sum(m.access_status == "failed" or m.scope == "none" for m in materials)
            items.append(
                {
                    "id": source.id,
                    "name": source.name,
                    "configured_owner": source.discovery_owner,
                    "stages": {
                        key: getattr(source.r1, key)
                        for key in ("discovery", "material", "paid", "publish")
                    },
                    "paid_material_scopes": source.r1.paid_scopes,
                    "publication_material_scopes": source.r1.publish_scopes,
                    "runtime_initialized": state is not None,
                    "runtime_owner": state.owner if state else None,
                    "last_success_at": state.last_success_at if state else None,
                    "last_new_item_at": state.last_new_item_at if state else None,
                    "next_due_at": state.next_due_at if state else None,
                    "consecutive_failures": state.consecutive_failures if state else None,
                    "sampled_material_versions": len(materials),
                    "failed_material_versions": failed,
                    "material_failure_fraction": failed / len(materials) if materials else None,
                    "failure_denominator": "latest_100_material_versions_not_distinct_contents",
                }
            )
        return {"items": items}
