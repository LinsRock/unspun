"""Shared legacy event scoring and impact assessment for explicit repair."""

import math
from datetime import UTC, datetime, timedelta
from statistics import mean
from typing import Any

from sqlalchemy.orm import Session

from unspun.core.config import get_settings
from unspun.core.content import require_legacy
from unspun.core.legacy_backlog import pending_score_conditions as pending_score_conditions
from unspun.core.llm import SupportsLlm
from unspun.core.models import Article, Event
from unspun.core.params import ScoringParams
from unspun.core.public_impact import (
    ImpactArticle,
    assess_impact,
    impact_fingerprint,
    unknown_impact,
)
from unspun.core.publication import publication_bounds
from unspun.core.sources import Source

PROMPT_ARTICLE_LIMIT = 8
PROMPT_SUMMARY_CHARS = 500

# Anchored rubric from docs/requirement.md (translated; repo content is English).
IMPORTANCE_SYSTEM = (
    "You rate how important a news event is, using anchored 1-5 integer scales. "
    "When unsure, pick the LOWER band. Cite facts from the provided sources.\n\n"
    "scope (who is affected):\n"
    "5 = global, hundreds of millions+ (pandemic, 2008 financial crisis)\n"
    "4 = multiple countries, or nationwide in a major power (surprise rate move, "
    "major-power election result)\n"
    "3 = one industry or one region (new industry regulation, flagship product launch)\n"
    "2 = a specific group or niche field (major OSS release, professional guideline update)\n"
    "1 = a single company or person (personnel change, celebrity news)\n\n"
    "durability (how long it matters):\n"
    "5 = reshapes a decade (ChatGPT launch)\n"
    "4 = years (landmark law passed, new drug approved)\n"
    "3 = months (policy adjustment, industry repricing)\n"
    "2 = weeks (one-off accident, interim poll)\n"
    "1 = forgotten in days (spat, gossip)\n\n"
    "novelty:\n"
    "5 = first-ever discovery or decision\n"
    "4 = substantial new development in a known story\n"
    "3 = new data or detail, direction already known\n"
    "2 = old news from a new angle, commentary\n"
    "1 = repeat coverage, nothing new\n\n"
    "domain_importance (1-5): how important practitioners in this field consider it; "
    "used for per-domain normalization, not the main formula.\n\n"
    'Respond with a JSON object: {"scope": n, "durability": n, "novelty": n, '
    '"domain_importance": n, "reason": "...", "confidence": "low|medium|high"}. '
    "reason is ONE sentence in Simplified Chinese citing a concrete fact from the sources."
)


def _clamp_band(value: Any) -> int:
    try:
        return max(1, min(5, int(value)))
    except (TypeError, ValueError):
        return 1


def objective_score(
    articles: list[Article],
    sources_by_id: dict[str, Source],
    params: ScoringParams,
    now: datetime | None = None,
) -> tuple[float, dict[str, float]]:
    """Breadth, growth, source quality, community heat -> 0-100 plus components."""
    now = now or datetime.now(UTC)
    cfg = params.objective_signals
    source_ids = {a.source_id for a in articles}
    known = [sources_by_id[sid] for sid in source_ids if sid in sources_by_id]
    source_count = len(source_ids)
    langs = {s.lang for s in known}
    regions = {s.region for s in known}
    # Log saturation (D-010): the old linear 20/source maxed out at five
    # sources, flattening local pileups and global stories alike.
    breadth = 100.0 * math.log1p(source_count) / math.log1p(cfg.source_cap)
    if known and len(known) == source_count and len(langs) <= 1 and len(regions) <= 1:
        # Every counted source is known and they all share one language
        # and one region: local heat is not global coverage. Sources
        # missing from config are not evidence of monolocality, so a
        # partial match never discounts.
        breadth *= cfg.monolocal_discount
    breadth = min(100.0, breadth)
    window_start = now - timedelta(hours=cfg.growth_window_hours)
    # published_at, not fetched_at: a backfill of old articles is not
    # growth, and neither is a feed's future-dated timestamp (<= now).
    recent_times = [a.published_at or a.fetched_at for a in articles]
    recent = sum(1 for t in recent_times if t and window_start <= t <= now)
    growth = min(100.0, 100.0 * math.log1p(recent) / math.log1p(cfg.recent_cap))
    quality = 100.0 * (mean(s.weight for s in known) if known else 0.5)
    community = 100.0 if any(s.kind == "community" for s in known) else 0.0
    w = params.objective
    score = (
        w.breadth * breadth
        + w.growth * growth
        + w.source_quality * quality
        + w.community * community
    )
    return score, {
        "breadth": breadth,
        "growth": growth,
        "source_quality": quality,
        "community": community,
    }


def importance_user_prompt(articles: list[Article], sources_by_id: dict[str, Source]) -> str:
    ranked = sorted(
        articles,
        key=lambda a: sources_by_id[a.source_id].weight if a.source_id in sources_by_id else 0.0,
        reverse=True,
    )[:PROMPT_ARTICLE_LIMIT]
    blocks: list[str] = [f"Event with {len(articles)} source articles:"]
    for a in ranked:
        source = sources_by_id.get(a.source_id)
        name = source.name if source else a.source_id
        summary = (a.summary_zh or a.content or "")[:PROMPT_SUMMARY_CHARS]
        blocks.append(f"- [{name}] {a.title_zh or a.title}\n  {summary}")
    return "\n".join(blocks)


def score_event(
    session: Session,
    client: SupportsLlm,
    event: Event,
    params: ScoringParams,
    sources_by_id: dict[str, Source],
) -> None:
    articles = list(event.articles)
    require_legacy(*articles)
    obj_score, obj_parts = objective_score(articles, sources_by_id, params)
    out = client.chat_json(
        session,
        model=get_settings().importance_model,
        system=IMPORTANCE_SYSTEM,
        user=importance_user_prompt(articles, sources_by_id),
        purpose="importance",
    )
    scope = _clamp_band(out.get("scope"))
    durability = _clamp_band(out.get("durability"))
    novelty = _clamp_band(out.get("novelty"))
    w_imp = params.importance
    importance = 20.0 * (
        w_imp.scope * scope + w_imp.durability * durability + w_imp.novelty * novelty
    )
    # M3 adds the relevance component; until then renormalize over active weights.
    w_final = params.final_score
    active = w_final.objective + w_final.importance
    final = (w_final.objective * obj_score + w_final.importance * importance) / active
    event.score_final = final
    event.score_breakdown = {
        "objective": {"score": obj_score, **obj_parts},
        "importance": {
            "score": importance,
            "scope": scope,
            "durability": durability,
            "novelty": novelty,
            "domain_importance": _clamp_band(out.get("domain_importance")),
            "reason": str(out.get("reason") or ""),
            "confidence": str(out.get("confidence") or "low"),
        },
    }
    now = datetime.now(UTC)
    refresh_event_public_impact(session, client, event, now)
    event.scored_at = now


def refresh_event_public_impact(
    session: Session,
    client: SupportsLlm,
    event: Event,
    now: datetime | None = None,
) -> bool:
    """Refresh eligible impact metadata, leaving importance scores untouched.

    Transient failures retry at most hourly, within the original 48-hour window.
    Evidence/payload failures remain cached until member inputs change.
    """
    require_legacy(*event.articles)
    now = now or datetime.now(UTC)
    articles = [a for a in event.articles if a.fetched_at <= now]
    original = [
        ImpactArticle(
            id=a.id,
            title=a.title,
            text=(a.content or "") if a.content_basis == "original" else "",
            reported_at=a.reported_at,
            reported_date=a.reported_date,
        )
        for a in articles
    ]
    model = get_settings().viewpoint_model
    fingerprint = impact_fingerprint(original, model)
    cached = event.public_impact
    same_input = bool(cached and cached.get("input_fingerprint") == fingerprint)
    bounds = [
        bound
        for a in articles
        if a.reported_precision != "unknown"
        and (
            bound := publication_bounds(
                a.reported_at if a.reported_precision == "time" else None,
                a.reported_date if a.reported_precision == "date" else None,
                a.fetched_at,
                now,
            )
        )
        is not None
    ]
    eligible = bool(
        bounds
        and min(bound[0] for bound in bounds) >= now - timedelta(hours=48)
        and any(a.text.strip() for a in original)
    )
    if not eligible:
        if same_input and cached and cached.get("failure_kind") == "ineligible":
            return False
        result = unknown_impact(
            "Original reporting is outside the current impact window or unavailable", "ineligible"
        )
        result.input_fingerprint = fingerprint
        result.model = model
        result.assessed_at = now
        event.public_impact = result.model_dump(mode="json")
        return True
    if same_input and cached:
        if cached.get("status") != "unknown" or cached.get("failure_kind") not in (
            "budget",
            "generation",
        ):
            return False
        try:
            assessed_at = datetime.fromisoformat(str(cached.get("assessed_at")))
            if assessed_at.utcoffset() is None or assessed_at > now - timedelta(hours=1):
                return False
        except ValueError:
            pass
    event.public_impact = assess_impact(session, client, original, now, model).model_dump(
        mode="json"
    )
    return True
