"""Read-only independent content routes, with one explicit idempotent guide request."""

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from unspun.api.admin.auth import require_admin_identity
from unspun.api.events import get_db
from unspun.api.feed_preferences import Db, require_write
from unspun.core.billing_models import BudgetPolicy
from unspun.core.config import get_settings
from unspun.core.content_feed import item_out, page
from unspun.core.content_publication import Item, qualified_item
from unspun.core.content_reading import GUIDE_VERSION, REVIEW_VERSION, GuideDraft, guide_valid
from unspun.core.hybrid_feed import page as hybrid_page
from unspun.core.models import Article, ContentDerivation
from unspun.core.reader import effective_feedback
from unspun.core.sources import load_sources
from unspun.core.task_models import PipelineTask
from unspun.pipeline.content_processing import enqueue_processing, processing_fingerprint
from unspun.pipeline.discovery import lock_identity

router = APIRouter(dependencies=[Depends(require_admin_identity)])
ReadDb = Annotated[Session, Depends(get_db)]


def local_preview(request: Request, session: Session) -> bool:
    settings = get_settings()
    if not settings.r1_local_preview:
        return False
    url = make_url(settings.database_url)
    policy = session.get(BudgetPolicy, 1)
    if not (
        settings.admin_local_preview
        and request.client
        and request.client.host in {"127.0.0.1", "::1"}
        and url.host in {"localhost", "127.0.0.1", "::1"}
        and (url.database or "").startswith("unspun_quality_")
        and policy
        and policy.scope == "evaluation"
    ):
        raise HTTPException(503, "R1 preview requires a loopback evaluation environment")
    return True


@router.get("/api/feed")
def feed(
    request: Request,
    session: ReadDb,
    mode: Literal["content", "mixed"] = "content",
    sort: Literal["recommended", "latest"] = "recommended",
    cursor: str | None = Query(default=None, max_length=2000),
    limit: int = Query(default=20, ge=1, le=50),
) -> dict[str, Any]:
    if mode == "mixed":
        return hybrid_page(session, sort=sort, cursor=cursor, limit=limit, now=datetime.now(UTC))
    return page(
        session,
        preview=local_preview(request, session),
        sort=sort,
        cursor=cursor,
        limit=limit,
        now=datetime.now(UTC),
    )


def find_item(session: Session, article_id: int, preview: bool) -> tuple[Item, int | None]:
    article = session.get(Article, article_id)
    if article is None or article.processing_track != "r1":
        raise HTTPException(404, "R1 content not found")
    requested = article_id
    visited: set[int] = set()
    while article.canonical_content_id:
        if article.id in visited or len(visited) >= 64:
            raise HTTPException(409, "Canonical content identity is inconsistent")
        visited.add(article.id)
        article = session.get(Article, article.canonical_content_id)
        if article is None or article.processing_track != "r1":
            raise HTTPException(404, "Canonical R1 content not found")
    sources = load_sources()
    item = qualified_item(
        session, article.id, preview=preview, as_of=datetime.now(UTC), sources=sources
    )
    if item is None:
        raise HTTPException(404, "Current reviewed R1 content is not published")
    return item, requested if requested != article.id else None


def guide_state(session: Session, item: Item) -> dict[str, Any]:
    expected = processing_fingerprint(item.content, "guide")
    row = session.scalar(
        select(ContentDerivation).where(
            ContentDerivation.article_id == item.article.id,
            ContentDerivation.kind == "guide",
            ContentDerivation.input_fingerprint == expected,
        )
    )
    task = session.scalar(
        select(PipelineTask)
        .where(
            PipelineTask.article_id == item.article.id,
            PipelineTask.kind == "process_guide",
            PipelineTask.input_fingerprint == expected,
        )
        .order_by(PipelineTask.id.desc())
        .limit(1)
    )
    source = next((s for s in load_sources() if s.id == item.article.source_id), None)
    requestable = bool(
        source
        and source.r1
        and source.r1.allows_paid(item.content.scope)
        and source.discovery_owner == "r1"
    )
    payload = None
    status, reason = "not_requested", None
    if row:
        status, reason = row.status, row.reason
        if status == "ready":
            try:
                parsed = GuideDraft.model_validate(
                    {k: v for k, v in (row.payload or {}).items() if k in GuideDraft.model_fields}
                )
                if (
                    row.material_id == item.content.material_id
                    and row.metadata_fingerprint == item.content.metadata_fingerprint
                    and row.contract_version == GUIDE_VERSION
                    and row.review_contract == REVIEW_VERSION
                    and (row.review_evidence or {}).get("approved") is True
                    and guide_valid(parsed, item.content)
                ):
                    payload = row.payload
                else:
                    status, reason = "failed", "guide_contract_invalid"
            except ValueError:
                status, reason = "failed", "guide_contract_invalid"
    if task and status != "ready" and status != "rejected":
        status = (
            task.status
            if task.status in {"failed", "blocked", "budget_deferred"}
            else "review_pending"
            if status == "review_pending"
            else "pending"
        )
        reason = task.last_error or reason
    if len(item.content.model_text()) < 300:
        status, reason = "unavailable", "insufficient_increment"
    elif not requestable and status not in {"ready", "rejected", "failed", "blocked"}:
        status, reason = "unavailable", "paid_stage_disabled"
    return {
        "status": status,
        "reason": reason,
        "payload": payload,
        "task_id": task.id if task else None,
        "requestable": requestable and task is None and status == "not_requested",
    }


@router.get("/api/contents/{article_id}")
def details(article_id: int, request: Request, session: ReadDb) -> dict[str, Any]:
    preview = local_preview(request, session)
    item, alias = find_item(session, article_id, preview)
    feedback = effective_feedback(session).get(item.article.id)
    out = item_out(item, {"feedback_value": feedback.value if feedback else None}, load_sources())
    out.update(
        preview=preview,
        requested_alias_id=alias,
        material={
            "scope": item.content.scope,
            "paragraphs": [p.model_dump() for p in item.content.paragraphs],
            "retrieved_at": item.content.material_observed_at,
            "extractor_version": item.content.extractor_version,
        },
        guide=guide_state(session, item),
    )
    return out


@router.post("/api/contents/{article_id}/guide", dependencies=[Depends(require_write)])
def request_guide(article_id: int, request: Request, session: Db) -> dict[str, Any]:
    # Single-user enqueue only: no network or model call under this short lock.
    lock_identity(session, "r1-guide-request")
    item, _ = find_item(session, article_id, local_preview(request, session))
    state = guide_state(session, item)
    if state["requestable"]:
        enqueue_processing(session, item.article.id, "guide")
        session.flush()
        state = guide_state(session, item)
    return {"content_id": item.article.id, **state}
