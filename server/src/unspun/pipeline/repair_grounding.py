"""Explicit event-scoped repair; defaults to a read-only dry run.

Generate on transient copies, commit billed usage after each call, then apply
all business changes atomically only if the input snapshot is still current.
Historical digest snapshots and the event's news timestamp are never changed.
"""

import argparse
import copy
import json
from typing import Any

import numpy as np
from sqlalchemy.orm import Session, selectinload

from unspun.core.config import get_settings
from unspun.core.db import get_engine
from unspun.core.llm import LlmClient, LlmError, SupportsLlm
from unspun.core.models import Article, Event, EventViewpoint
from unspun.core.params import get_scoring_params
from unspun.core.review_budget import require_grounding_budget
from unspun.core.sources import load_sources
from unspun.pipeline.score import score_event
from unspun.pipeline.summarize import embed_articles, summarize_article
from unspun.pipeline.viewpoints import input_fingerprint, refresh_event_viewpoint


class UsageCommittingClient:
    def __init__(self, delegate: SupportsLlm, max_calls: int) -> None:
        self.delegate = delegate
        self.max_calls = max_calls
        self.calls = 0

    def _reserve(self) -> None:
        if self.calls >= self.max_calls:
            raise LlmError("repair logical call cap reached")
        self.calls += 1

    def chat_json(
        self,
        session: Session,
        *,
        model: str,
        system: str,
        user: str,
        purpose: str,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        self._reserve()
        try:
            return self.delegate.chat_json(
                session,
                model=model,
                system=system,
                user=user,
                purpose=purpose,
                max_tokens=max_tokens,
            )
        finally:
            session.commit()

    def embed(self, session: Session, texts: list[str]) -> list[list[float]]:
        self._reserve()
        try:
            return self.delegate.embed(session, texts)
        finally:
            session.commit()


def copy_article(article: Article) -> Article:
    fields = (
        "id",
        "source_id",
        "url",
        "title",
        "title_zh",
        "content",
        "lang",
        "published_at",
        "fetched_at",
        "summary_zh",
        "summary_grounding",
        "embedding",
        "summary_failures",
    )
    return Article(**{field: copy.deepcopy(getattr(article, field)) for field in fields})


def repair_event(
    session: Session,
    client: SupportsLlm | None,
    event_id: int,
    *,
    apply: bool = False,
    max_articles: int = 100,
    max_calls: int = 250,
) -> dict[str, Any]:
    if max_articles <= 0 or max_calls <= 0:
        raise ValueError("repair caps must be positive")
    event = session.get(
        Event, event_id, options=[selectinload(Event.articles), selectinload(Event.viewpoint)]
    )
    if event is None:
        raise ValueError(f"event {event_id} not found")
    originals = sorted(event.articles, key=lambda a: a.id)
    if not originals:
        raise ValueError("event has no source articles")
    if len(originals) > max_articles:
        raise ValueError("event exceeds repair article cap")
    result: dict[str, Any] = {
        "event_id": event_id,
        "article_ids": [a.id for a in originals],
        "applied": False,
        "preserves_digest_snapshots": True,
        "preserves_event_time": True,
    }
    if not apply:
        return result
    require_grounding_budget(session)
    # Every paid stage below sees only transient copies. No application row is
    # dirty when UsageCommittingClient commits its usage ledger.
    sources = {source.id: source for source in load_sources()}
    model = get_settings().viewpoint_model
    before = input_fingerprint(originals, sources, model)
    working = Event(
        id=event.id,
        title=event.title,
        summary_zh=event.summary_zh,
        changed_at=event.changed_at,
        first_seen_at=event.first_seen_at,
        articles=[copy_article(article) for article in originals],
    )
    if event.viewpoint is not None:
        working.viewpoint = EventViewpoint(
            payload=copy.deepcopy(event.viewpoint.payload),
            model=event.viewpoint.model,
            input_fingerprint=event.viewpoint.input_fingerprint,
            generated_at=event.viewpoint.generated_at,
        )
    if client is None:
        raise ValueError("apply requires an LLM client")
    billed = UsageCommittingClient(client, max_calls)
    for article in working.articles:
        summarize_article(session, billed, article)
        if (article.summary_grounding or {}).get("status") == "review_limited":
            raise LlmError("repair review budget exhausted; original event retained")
    embed_articles(session, billed, list(working.articles))
    vectors = np.asarray([a.embedding for a in working.articles], dtype=np.float64)
    centroid = vectors.mean(axis=0)
    norm = float(np.linalg.norm(centroid))
    working.centroid = (centroid / norm if norm > 0 else centroid).tolist()
    representative = min(working.articles, key=lambda a: a.id)
    working.title = representative.title_zh or representative.title
    working.summary_zh = representative.summary_zh
    params = get_scoring_params()
    score_event(session, billed, working, params, sources)
    status = refresh_event_viewpoint(session, billed, working, params.viewpoints, sources)
    if status == "rejected" or (
        working.viewpoint is not None
        and working.viewpoint.payload.get("status") == "review_limited"
    ):
        raise LlmError("repair viewpoint rejected; original event retained")
    session.expire_all()
    current = session.get(
        Event,
        event_id,
        options=[selectinload(Event.articles), selectinload(Event.viewpoint)],
        populate_existing=True,
        with_for_update=True,
    )
    if current is None or input_fingerprint(list(current.articles), sources, model) != before:
        session.rollback()
        raise LlmError("event inputs changed during repair; original event retained")
    try:
        by_id = {article.id: article for article in current.articles}
        for replacement in working.articles:
            article = by_id[replacement.id]
            for field in ("title_zh", "summary_zh", "summary_grounding", "embedding"):
                setattr(article, field, copy.deepcopy(getattr(replacement, field)))
            article.summary_failures = 0
        for field in (
            "title",
            "summary_zh",
            "centroid",
            "score_final",
            "score_breakdown",
            "scored_at",
        ):
            setattr(current, field, copy.deepcopy(getattr(working, field)))
        if working.viewpoint is not None:
            if current.viewpoint is None:
                current.viewpoint = EventViewpoint(
                    payload=copy.deepcopy(working.viewpoint.payload),
                    model=working.viewpoint.model,
                    input_fingerprint=working.viewpoint.input_fingerprint,
                    generated_at=working.viewpoint.generated_at,
                )
            else:
                for field in ("payload", "model", "input_fingerprint", "generated_at"):
                    setattr(
                        current.viewpoint, field, copy.deepcopy(getattr(working.viewpoint, field))
                    )
        session.commit()
    except Exception:
        session.rollback()
        raise
    result.update(applied=True, logical_calls=billed.calls, viewpoint_status=status)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-id", type=int, action="append", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--max-articles", type=int, default=100)
    parser.add_argument("--max-calls", type=int, default=250)
    args = parser.parse_args()
    # Dry-run must not initialize an authenticated client or invoke the LLM.
    with Session(get_engine()) as session:
        for event_id in dict.fromkeys(args.event_id):
            if not args.apply:
                print(
                    json.dumps(
                        repair_event(session, None, event_id, max_articles=args.max_articles)
                    )
                )
            else:
                with LlmClient() as client:
                    print(
                        json.dumps(
                            repair_event(
                                session,
                                client,
                                event_id,
                                apply=True,
                                max_articles=args.max_articles,
                                max_calls=args.max_calls,
                            )
                        )
                    )


if __name__ == "__main__":
    main()
