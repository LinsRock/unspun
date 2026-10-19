"""Short-transaction R2 selection receipts; physical costs stay in the R1 journal."""

from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from unspun.core.content import ContentMetadata, fingerprint
from unspun.core.content_reading import CARD_VERSION, cheap_exclusion, publication_at
from unspun.core.models import Article, ContentMaterial
from unspun.core.sources import Source
from unspun.core.task_models import DiscoveryBatch, PipelineTask
from unspun.core.tasks import enqueue
from unspun.pipeline.discovery import MATERIAL_VERSION, lock_identity

VERSION = "r2-discovery-v2"


def selection_lock(session: Session) -> None:
    # Use the same lock order in discovery and material completion. No network
    # requests occur while this bounded selection transaction holds the lock.
    lock_identity(session, "r2:discovery-selection")


def record_processing(batch: DiscoveryBatch, key: str, outcome: dict[str, Any]) -> dict[str, Any]:
    batch.paid_outcomes = {**batch.paid_outcomes, key: outcome}
    reasons = [value["reason"] for value in batch.paid_outcomes.values()]
    batch.counters = {
        **batch.counters,
        "paid_counts": {reason: reasons.count(reason) for reason in sorted(set(reasons))},
    }
    return outcome


def metadata_exclusion(
    source: Source, metadata: ContentMetadata, url: str, now: datetime
) -> str | None:
    assert source.r1
    host = urlsplit(url).hostname or ""
    if not any(host == h or host.endswith("." + h) for h in source.r1.origin_hosts):
        return "material_origin_disabled"
    at = publication_at(metadata)
    if source.r1.material_scope == "complete_brief" and at and now - at > timedelta(hours=48):
        return "stale_brief"
    if metadata.genre in {"old_report", "news"} and at and now - at > timedelta(days=14):
        return "stale_report"
    return None


def select_materials(
    session: Session,
    source: Source,
    batch: DiscoveryBatch,
    candidates: list[tuple[Article, dict[str, Any], str | None]],
) -> None:
    assert source.r1 and source.r1.quotas
    quota = source.r1.quotas
    waiting: list[tuple[Article, dict[str, Any]]] = []
    refresh: list[tuple[datetime, Article, dict[str, Any]]] = []
    decisions: dict[str, Any] = {}
    for article, payload, excluded in candidates:
        key = str(article.id)
        if not source.r1.material or excluded:
            decisions[key] = excluded or "material_disabled"
            continue
        previous = session.scalar(
            select(PipelineTask)
            .where(PipelineTask.article_id == article.id, PipelineTask.kind == "fetch_material")
            .order_by(PipelineTask.id.desc())
            .limit(1)
        )
        if previous is None:
            waiting.append((article, payload))
            continue
        # Page-enriched canonical metadata is not a new list observation.
        changed = any(
            previous.payload.get(key) != value
            for key, value in payload.items()
            if key != "metadata"
        )
        if not changed and previous.status in {
            "pending",
            "running",
            "retry_wait",
            "budget_deferred",
            "blocked",
        }:
            decisions[key] = "material_inflight_reused"
        elif changed or batch.observed_at - previous.created_at >= timedelta(
            seconds=quota.recheck_seconds
        ):
            refresh.append((previous.created_at, article, payload))
        else:
            decisions[key] = "recheck_not_due"
    waiting.sort(key=lambda value: (value[0].fetched_at, value[0].id))
    refresh.sort(key=lambda value: (value[0], value[1].id))
    previous_batch = session.scalar(
        select(DiscoveryBatch)
        .where(
            DiscoveryBatch.source_id == source.id,
            DiscoveryBatch.id < batch.id,
            DiscoveryBatch.material_tasks != [],
        )
        .order_by(DiscoveryBatch.id.desc())
        .limit(1)
    )
    previous_refresh = (
        previous_batch
        and "recheck_selected" in previous_batch.counters.get("material_decisions", {}).values()
    )
    # A single slot alternates when both queues need work. Large due sets must
    # neither starve new identities nor permanently lose their update checks.
    take_refresh = bool(
        quota.material and refresh and not (quota.material == 1 and waiting and previous_refresh)
    )
    chosen = [(a, p, "recheck_selected") for _, a, p in refresh[:1]] if take_refresh else []
    chosen += [
        (a, p, "new_material_selected") for a, p in waiting[: max(0, quota.material - len(chosen))]
    ]
    remaining = quota.material - len(chosen)
    start = 1 if take_refresh else 0
    chosen += [(a, p, "recheck_selected") for _, a, p in refresh[start : start + remaining]]
    for article, _ in waiting:
        decisions.setdefault(str(article.id), "material_quota_deferred")
    for _, article, _ in refresh:
        decisions.setdefault(str(article.id), "material_quota_deferred")
    task_ids: list[int] = []
    for article, payload, reason in chosen:
        task_ids.append(
            enqueue(
                session,
                queue="material",
                kind="fetch_material",
                object_key=f"content:{article.id}",
                article_id=article.id,
                source_id=source.id,
                input_fingerprint=fingerprint(payload),
                strategy_version=MATERIAL_VERSION,
                cycle_key=f"r2:{batch.id}",
                payload={**payload, "quota_batch_id": batch.id},
            )
        )
        decisions[str(article.id)] = reason
    batch.material_tasks = task_ids
    batch.counters = {
        **batch.counters,
        "material_selected": len(task_ids),
        "material_decisions": decisions,
    }


def select_processing(
    session: Session, source: Source, batch: DiscoveryBatch, article_id: int
) -> dict[str, Any]:
    from unspun.pipeline.content_processing import (
        enqueue_processing,
        load_content,
        processing_fingerprint,
    )

    assert source.r1
    article = session.get(Article, article_id)
    current = (
        session.get(ContentMaterial, article.current_material_id)
        if article and article.current_material_id
        else None
    )
    if (
        current is None
        or article is None
        or current.metadata_fingerprint != article.metadata_fingerprint
    ):
        return {"reason": "material_not_current"}
    content = load_content(session, article_id)
    input_fp = processing_fingerprint(content, "card")
    key = f"{article_id}:{input_fp}"
    old = batch.paid_outcomes.get(key)
    if old is not None and "task_id" in old:
        return dict(old)
    excluded = cheap_exclusion(content, batch.observed_at)
    if not source.r1.allows_paid(current.scope) or excluded:
        outcome = {"reason": excluded or "paid_material_scope_disabled"}
        return record_processing(batch, key, outcome)
    existing = session.scalar(
        select(PipelineTask.id).where(
            PipelineTask.kind == "process_card",
            PipelineTask.article_id == article_id,
            PipelineTask.input_fingerprint == input_fp,
            PipelineTask.strategy_version == CARD_VERSION,
        )
    )
    used = sum(value.get("reason") == "paid_selected" for value in batch.paid_outcomes.values())
    if existing is None and used >= int(batch.quotas["paid"]):
        outcome = {"reason": "paid_quota_deferred"}
        return record_processing(batch, key, outcome)
    task_id = enqueue_processing(session, article_id)
    outcome = {"task_id": task_id, "reason": "paid_reused" if existing else "paid_selected"}
    return record_processing(batch, key, outcome)
