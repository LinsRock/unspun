"""Read a currently publishable topic by identity, independent of feed recall."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from unspun.core.content_feed import item_out
from unspun.core.content_publication import qualified_item
from unspun.core.hybrid_ranking import time_key
from unspun.core.sources import Source
from unspun.core.synthesis_models import TopicSynthesis
from unspun.core.topic_models import Topic
from unspun.core.topic_synthesis import qualified_topic_text
from unspun.core.topics import topic_snapshot


def topic_detail(
    session: Session, topic_id: UUID, *, sources: list[Source], now: datetime
) -> dict[str, Any] | None:
    try:
        view = qualified_topic_text(session, topic_id, sources=sources, now=now)
        if view is None:
            return None
        topic = session.get(Topic, str(topic_id), populate_existing=True)
        synthesis = session.get(TopicSynthesis, view["version"])
        if topic is None or topic.status != "active" or synthesis is None:
            return None
        snapshot = topic_snapshot(session, topic, sources, now)
        related: list[dict[str, Any]] = []
        for member in snapshot["members"]:
            item = qualified_item(
                session, member["article_id"], preview=False, as_of=now, sources=sources
            )
            if item is None:
                return None
            related.append({**item_out(item, {}, sources), "relation": member["relation"]})
        progress = [
            {
                **u["row"]["payload"],
                "text": u["row"]["payload"]["summary"],
                "revision": u["row"]["revision"],
            }
            for u in snapshot["updates"]
            if u["check"]["valid"]
            and u["row"]["payload"].get("classification") in {"development", "discussion_focus"}
        ]
        progress.sort(
            key=lambda p: time_key(
                p["occurred"] if p["occurred"]["precision"] != "unknown" else p["reported"]
            ),
            reverse=True,
        )
        return {
            "id": topic.id,
            "title": topic.title,
            "kind": topic.kind,
            "domains": topic.domains,
            "version": view["version"],
            "revision": topic.revision,
            "overview": view["overview"],
            "guide": view["guide"],
            "progress": progress,
            "context": [
                c
                for c in synthesis.draft["contributions"]
                if c["classification"] in {"background", "opinion"}
            ],
            "related": related,
            "engineering_preview": False,
        }
    except (ValueError, KeyError, TypeError):
        # Invalid current dependencies never fall back to retained old prose.
        return None
