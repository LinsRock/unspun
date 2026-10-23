"""Opt-in, read-only hybrid API with dependency-fenced pagination."""

import base64
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from unspun.core.config import get_settings
from unspun.core.content import fingerprint
from unspun.core.content_feed import rules
from unspun.core.hybrid_contracts import VERSION, HybridCursor, hybrid_rules
from unspun.core.hybrid_ranking import ordered, render_page
from unspun.core.hybrid_recall import content_candidates, topic_candidates
from unspun.core.reader_models import ReaderInterest
from unspun.core.sources import load_sources


def _cursor(value: str, sort: str, limit: int, now: datetime) -> HybridCursor:
    try:
        if len(value) > 2000:
            raise ValueError("cursor too large")
        token = HybridCursor.model_validate_json(
            base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        )
        if (
            token.sort != sort
            or token.page_size != limit
            or not timedelta(0) <= now - token.as_of <= timedelta(minutes=15)
        ):
            raise ValueError("cursor expired or order/page size changed")
        return token
    except ValueError as error:
        raise HTTPException(400, "Invalid or expired hybrid cursor") from error


def page(
    session: Session,
    *,
    sort: Literal["recommended", "latest"],
    cursor: str | None,
    limit: int,
    now: datetime,
) -> dict[str, Any]:
    if not get_settings().r2_hybrid_enabled:
        raise HTTPException(404, "Hybrid feed is disabled")
    if not 1 <= limit <= 50:
        raise HTTPException(400, "Invalid hybrid page size")
    token = _cursor(cursor, sort, limit, now) if cursor else None
    as_of = token.as_of if token else now
    policy, reader, sources = hybrid_rules(), rules(), load_sources()
    interests = list(
        session.scalars(select(ReaderInterest).order_by(ReaderInterest.resource_key).limit(257))
    )
    if len(interests) > 256:
        raise HTTPException(503, "Hybrid interest recall exceeds the registered 256-resource bound")
    contents, content_counts, reader_snapshot = content_candidates(
        session, sources, policy, interests, now, as_of
    )
    topics, topic_counts = (
        topic_candidates(session, sources, policy, interests, now)
        if get_settings().r2_topic_publication_enabled
        else ([], {})
    )
    candidates = contents + topics
    snapshot = fingerprint(
        {
            "version": VERSION,
            "policy": policy.model_dump(mode="json"),
            "reader": reader_snapshot,
            "sources": [s.model_dump(mode="json") for s in sources],
            "topic_publication": get_settings().r2_topic_publication_enabled,
            "candidates": [
                {
                    **asdict(c),
                    "signals": {k: v.model_dump(mode="json") for k, v in c.signals.items()},
                }
                for c in candidates
            ],
        }
    )
    if token and token.snapshot != snapshot:
        raise HTTPException(409, "hybrid_changed_restart")
    rows = ordered(candidates, sort, policy, reader)
    offset = token.offset if token else 0
    if offset > len(rows):
        raise HTTPException(400, "Cursor offset exceeds the hybrid snapshot")
    end = offset + limit
    next_token = (
        HybridCursor(sort=sort, as_of=as_of, snapshot=snapshot, offset=end, page_size=limit)
        if end < len(rows)
        else None
    )
    return {
        "version": VERSION,
        "ranking_version": VERSION,
        "mode": "mixed",
        "sort": sort,
        "as_of": as_of,
        "snapshot": snapshot,
        "items": render_page(rows[offset:end]),
        "next_cursor": base64.urlsafe_b64encode(next_token.model_dump_json().encode())
        .decode()
        .rstrip("=")
        if next_token
        else None,
        "empty_reason": None if rows else "no_qualified_candidates",
        "recall": {
            "content_selected_by_lane": content_counts,
            "topic_selected_by_lane": topic_counts,
            "content_candidates": len(contents),
            "topic_candidates": len(topics),
            "bounded": True,
            "outside_boundary": "not_evaluated",
        },
    }
