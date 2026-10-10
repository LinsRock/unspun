"""Viewpoint comparison for events with diverse enough coverage (D-011).

Only events passing the diversity gate get an LLM call, and only when their
article set changed since the last generation (input fingerprint). Each claim
in the output carries the article_id it came from, so the frontend can link
every statement back to its source.
"""

import hashlib
from datetime import UTC, datetime
from typing import Any, Literal, cast

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from unspun.core.config import get_settings
from unspun.core.db import session_scope
from unspun.core.llm import LlmError, SupportsLlm
from unspun.core.logging import get_logger
from unspun.core.models import Article, Event, EventViewpoint
from unspun.core.params import ViewpointsParams, get_scoring_params
from unspun.core.sources import Source, load_sources

log = get_logger("unspun.pipeline.viewpoints")

# One article per source in the prompt; more sources than this and the
# cheapest-weighted ones are dropped rather than growing the prompt.
PROMPT_SOURCE_LIMIT = 12
PROMPT_SUMMARY_CHARS = 500
PROMPT_LEAD_CHARS = 300
# Upper bound on candidates examined per cycle. Ineligible events (e.g.
# monoculture coverage) stay candidates until their articles change, so
# without a cap the per-cycle scan would grow with database size.
CANDIDATE_SCAN_LIMIT = 200

RefreshStatus = Literal["skipped", "rejected", "generated"]

VIEWPOINT_SYSTEM = (
    "You compare how different news sources report the same event. "
    "Each input article is one source's coverage, labeled with its article_id. "
    'Respond with a JSON object: {"claims": [{"article_id": n, "claim": "..."}], '
    '"disagreements": [{"point": "...", "claim_indexes": [i, ...]}]}.\n'
    "- claims: one entry per article, in any order. claim is ONE sentence in "
    "Simplified Chinese stating that source's stance or central assertion — "
    "what THIS source emphasizes or claims, not a neutral summary of the event. "
    "Use only the provided article_id values.\n"
    "- disagreements: points where sources genuinely differ (facts, framing, "
    "attribution of blame, projected impact). point is 1-2 sentences in "
    "Simplified Chinese; claim_indexes are 0-based indexes into your claims "
    "list, at least two per point. An empty list is correct when sources agree."
)


def input_fingerprint(article_ids: list[int]) -> str:
    """Stable hash of the event's article id set; same set, same fingerprint."""
    joined = ",".join(str(i) for i in sorted(article_ids))
    return hashlib.sha256(joined.encode("ascii")).hexdigest()


def is_eligible(
    articles: list[Article], sources_by_id: dict[str, Source], params: ViewpointsParams
) -> bool:
    """Diversity gate: enough independent sources spanning regions or kinds.

    Sources missing from config still count as independent coverage but
    cannot prove diversity, mirroring the objective-score treatment.
    """
    source_ids = {a.source_id for a in articles}
    if len(source_ids) < params.min_sources:
        return False
    known = [sources_by_id[sid] for sid in source_ids if sid in sources_by_id]
    regions = {s.region for s in known}
    kinds = {s.kind for s in known}
    return len(regions) >= params.min_regions or len(kinds) >= params.min_kinds


def prompt_articles(articles: list[Article], sources_by_id: dict[str, Source]) -> list[Article]:
    """Latest article per source, highest-weight sources first, capped."""
    latest_per_source: dict[str, Article] = {}
    for a in articles:
        current = latest_per_source.get(a.source_id)
        a_time = a.published_at or a.fetched_at
        c_time = current.published_at or current.fetched_at if current else None
        if current is None or (a_time and (c_time is None or a_time > c_time)):
            latest_per_source[a.source_id] = a

    def weight(article: Article) -> float:
        source = sources_by_id.get(article.source_id)
        return source.weight if source else 0.0

    return sorted(latest_per_source.values(), key=weight, reverse=True)[:PROMPT_SOURCE_LIMIT]


def viewpoint_user_prompt(
    articles: list[Article], sources_by_id: dict[str, Source], source_count: int
) -> str:
    blocks = [
        f"Event covered by {source_count} sources; latest article from each of {len(articles)}:"
    ]
    for a in articles:
        source = sources_by_id.get(a.source_id)
        name = source.name if source else a.source_id
        summary = (a.summary_zh or "")[:PROMPT_SUMMARY_CHARS]
        lead = (a.content or "")[:PROMPT_LEAD_CHARS]
        blocks.append(
            f"article_id={a.id} [{name}] {a.title_zh or a.title}\n"
            f"  summary: {summary}\n"
            f"  lead: {lead}"
        )
    return "\n".join(blocks)


def parse_viewpoints_payload(out: dict[str, Any], allowed_ids: set[int]) -> dict[str, Any]:
    """Validate the model output into the stored payload shape.

    Claims with unknown or repeated article_ids are dropped (every statement
    must be traceable to exactly one article of this event); disagreement
    indexes are remapped to the kept claims and points left with fewer than
    two sides are dropped.
    """
    raw_claims = out.get("claims")
    raw_disagreements = out.get("disagreements")
    if not isinstance(raw_claims, list):
        raise LlmError("viewpoint output has no claims list")
    claims: list[dict[str, Any]] = []
    index_map: dict[int, int] = {}
    seen_ids: set[int] = set()
    for i, item in enumerate(cast("list[Any]", raw_claims)):
        if not isinstance(item, dict):
            continue
        entry = cast("dict[str, Any]", item)
        article_id = entry.get("article_id")
        claim = str(entry.get("claim") or "").strip()
        if not isinstance(article_id, int) or article_id not in allowed_ids or not claim:
            continue
        if article_id in seen_ids:  # one claim per article; keep the first
            continue
        seen_ids.add(article_id)
        index_map[i] = len(claims)
        claims.append({"article_id": article_id, "claim": claim})
    if len(claims) < 2:
        raise LlmError(f"only {len(claims)} traceable claims in viewpoint output")
    disagreements: list[dict[str, Any]] = []
    raw_list = cast("list[Any]", raw_disagreements) if isinstance(raw_disagreements, list) else []
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        entry = cast("dict[str, Any]", item)
        point = str(entry.get("point") or "").strip()
        raw_indexes = entry.get("claim_indexes")
        if not point or not isinstance(raw_indexes, list):
            continue
        indexes = sorted(
            {
                index_map[i]
                for i in cast("list[Any]", raw_indexes)
                if isinstance(i, int) and i in index_map
            }
        )
        if len(indexes) < 2:
            continue
        disagreements.append({"point": point, "claim_indexes": indexes})
    return {"claims": claims, "disagreements": disagreements}


def refresh_event_viewpoint(
    session: Session,
    client: SupportsLlm,
    event: Event,
    params: ViewpointsParams,
    sources_by_id: dict[str, Source],
) -> RefreshStatus:
    """Generate or replace the event's viewpoint row.

    Returns "skipped" (no LLM call: gate failed or article set unchanged),
    "rejected" (LLM ran but its output was unusable; the usage row must
    survive, so this commits instead of raising — D-007), or "generated".
    """
    articles = list(event.articles)
    if not is_eligible(articles, sources_by_id, params):
        return "skipped"
    fingerprint = input_fingerprint([a.id for a in articles])
    existing = event.viewpoint
    if existing is not None and existing.input_fingerprint == fingerprint:
        return "skipped"
    selected = prompt_articles(articles, sources_by_id)
    source_count = len({a.source_id for a in articles})
    model = get_settings().viewpoint_model
    out = client.chat_json(
        session,
        model=model,
        system=VIEWPOINT_SYSTEM,
        user=viewpoint_user_prompt(selected, sources_by_id, source_count),
        purpose="viewpoint",
        max_tokens=2048,
    )
    try:
        payload = parse_viewpoints_payload(out, {a.id for a in selected})
    except LlmError as exc:
        log.warning("viewpoint_output_rejected", event_id=event.id, error=str(exc))
        return "rejected"
    # Same clock as Event.changed_at (set in cluster.py); mixing the Python
    # and database clocks would skew the staleness comparison.
    now = datetime.now(UTC)
    if existing is not None:
        existing.payload = payload
        existing.input_fingerprint = fingerprint
        existing.model = model
        existing.generated_at = now
    else:
        event.viewpoint = EventViewpoint(
            payload=payload, input_fingerprint=fingerprint, model=model, generated_at=now
        )
    return "generated"


def candidate_viewpoint_ids(session: Session, min_sources: int) -> list[int]:
    """Events worth a look: enough distinct sources, and no viewpoint yet or
    changed since the last one. The diversity gate and fingerprint check
    happen per event; most recently changed events go first."""
    stale = or_(EventViewpoint.id.is_(None), Event.changed_at > EventViewpoint.generated_at)
    return list(
        session.scalars(
            select(Event.id)
            .join(Article, Article.event_id == Event.id)
            .outerjoin(EventViewpoint, EventViewpoint.event_id == Event.id)
            .where(stale)
            .group_by(Event.id)
            .having(func.count(func.distinct(Article.source_id)) >= min_sources)
            .order_by(Event.changed_at.desc())
            .limit(CANDIDATE_SCAN_LIMIT)
        )
    )


def viewpoints_pending(client: SupportsLlm, limit: int | None = None) -> int:
    """Run the viewpoint stage; returns the number of viewpoints generated.

    The batch limit counts LLM attempts (successful or not), not successes,
    so a run of unusable outputs cannot make per-cycle spend unbounded.
    """
    params = get_scoring_params().viewpoints
    if limit is None:
        limit = params.viewpoint_batch_limit
    sources_by_id = {s.id: s for s in load_sources()}
    with session_scope() as session:
        ids = candidate_viewpoint_ids(session, params.min_sources)
    attempts = 0
    generated = 0
    for event_id in ids:
        if attempts >= limit:
            break
        try:
            with session_scope() as session:
                event = session.get(
                    Event,
                    event_id,
                    options=[selectinload(Event.articles), selectinload(Event.viewpoint)],
                )
                if event is None:
                    continue
                status = refresh_event_viewpoint(session, client, event, params, sources_by_id)
            if status != "skipped":
                attempts += 1
            if status == "generated":
                generated += 1
        except Exception:
            # The LLM may have been called before the failure; count the
            # attempt so transport errors cannot unbound per-cycle spend.
            attempts += 1
            log.exception("viewpoint_failed", event_id=event_id)
    log.info("viewpoints_finished", candidates=len(ids), attempts=attempts, generated=generated)
    return generated
