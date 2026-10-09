"""Event scoring: objective signals computed in code, importance from the LLM rubric.

Only events whose content changed since the last scoring are (re)scored, so
LLM spend tracks real news flow instead of total event count.
"""

from datetime import UTC, datetime, timedelta
from statistics import mean
from typing import Any

from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.orm import Session, selectinload

from unspun.core.config import get_settings
from unspun.core.db import session_scope
from unspun.core.llm import SupportsLlm
from unspun.core.logging import get_logger
from unspun.core.models import Article, Event
from unspun.core.params import ScoringParams, get_scoring_params
from unspun.core.sources import Source, load_sources

log = get_logger("unspun.pipeline.score")

SCORE_BATCH_LIMIT = 40  # events per cycle, bounds one cycle's spend
GROWTH_WINDOW_HOURS = 24
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
    known = [sources_by_id[sid] for sid in {a.source_id for a in articles} if sid in sources_by_id]
    source_count = len({a.source_id for a in articles})
    langs = {s.lang for s in known}
    regions = {s.region for s in known}
    breadth = min(
        100.0,
        20.0 * source_count + 10.0 * max(0, len(langs) - 1) + 10.0 * max(0, len(regions) - 1),
    )
    window_start = now - timedelta(hours=GROWTH_WINDOW_HOURS)
    recent = sum(1 for a in articles if a.fetched_at and a.fetched_at >= window_start)
    growth = min(100.0, 20.0 * recent)
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
    event.scored_at = datetime.now(UTC)


def pending_score_conditions() -> tuple[ColumnElement[bool], ...]:
    # Shared with the daily report so the backlog count matches this query.
    return (or_(Event.scored_at.is_(None), Event.changed_at > Event.scored_at),)


def score_pending(client: SupportsLlm, limit: int = SCORE_BATCH_LIMIT) -> int:
    params = get_scoring_params()
    sources_by_id = {s.id: s for s in load_sources()}
    with session_scope() as session:
        ids = list(
            session.scalars(
                select(Event.id)
                .where(*pending_score_conditions())
                .order_by(Event.changed_at.desc())
                .limit(limit)
            )
        )
    done = 0
    for event_id in ids:
        try:
            with session_scope() as session:
                event = session.get(Event, event_id, options=[selectinload(Event.articles)])
                if event is None:
                    continue
                score_event(session, client, event, params, sources_by_id)
                done += 1
        except Exception:
            log.exception("score_failed", event_id=event_id)
    return done
