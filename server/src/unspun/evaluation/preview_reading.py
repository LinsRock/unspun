"""Isolated reading preview: archived production observations + labelled fixtures.

No provider calls or worker. Real snapshots have no recorded title-review proof
and remain withheld. Synthetic approvals exercise the UI only, never accuracy.
"""

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from unspun.core.config import get_settings
from unspun.core.db import get_engine
from unspun.core.models import Article, Event
from unspun.core.reading import attach_reading

ROOT = Path(__file__).resolve().parents[4]
SNAPSHOT: dict[str, Any] = json.loads(
    (ROOT / "docs/evaluations/m3b/production-candidates.json").read_text()
)
AS_OF = datetime.fromisoformat(SNAPSHOT["captured_at"])


def require_preview_database() -> None:
    url = make_url(get_settings().database_url)
    if url.host not in {"localhost", "127.0.0.1"} or url.database != "unspun_preview_reading":
        raise ValueError("requires the isolated local unspun_preview_reading database")


require_preview_database()
from unspun.api.app import app  # noqa: E402
from unspun.api.events import get_feed_now  # noqa: E402

app.dependency_overrides[get_feed_now] = lambda: AS_OF


def seed() -> None:
    require_preview_database()
    fixtures = json.loads((ROOT / "docs/design/reading/preview-cases.json").read_text())
    with Session(get_engine()) as session:
        if session.scalar(select(func.count()).select_from(Article)) or session.scalar(
            select(func.count()).select_from(Event)
        ):
            raise ValueError("preview seed requires an empty database")
        for raw in SNAPSHOT["events"]:
            event = Event(
                id=raw["id"],
                title=raw["title"],
                summary_zh=raw["summary_zh"],
                score_final=raw["score_final"],
                first_seen_at=datetime.fromisoformat(raw["first_seen_at"]),
                changed_at=datetime.fromisoformat(raw["changed_at"]),
            )
            session.add(event)
            for item in raw["articles"]:
                session.add(
                    Article(
                        id=item["id"],
                        title=item["title"],
                        url=item["url"],
                        source_id=item["source_id"],
                        event=event,
                        fetched_at=datetime.fromisoformat(item["fetched_at"]),
                        published_at=datetime.fromisoformat(item["published_at"])
                        if item["published_at"]
                        else None,
                    )
                )
        for row in fixtures["events"]:
            instant = AS_OF - timedelta(hours=row["hours"] + 1)
            event = Event(
                id=row["id"],
                title=row["title"],
                summary_zh=row["title"],
                score_final=row["score"],
                first_seen_at=instant,
                changed_at=instant,
                score_breakdown={
                    "importance": {
                        "score": row["score"],
                        "scope": 2,
                        "durability": 2,
                        "novelty": 3,
                        "domain_importance": 2,
                        "confidence": "medium",
                        "reason": row.get("reason", ""),
                    }
                },
            )
            session.add(event)
            for index, item in enumerate(row["articles"]):
                article = Article(
                    id=row["id"] * 10 + index,
                    event=event,
                    title=row["title"],
                    title_zh=row["title"],
                    summary_zh=" ".join(item["facts"]),
                    content="\n".join(item["facts"]),
                    source_id=item["source"],
                    url=f"https://example.org/preview/{row['id']}/{index}",
                    lang="zh",
                    content_basis="original",
                    fetched_at=instant,
                    reported_at=None if row.get("unknown_time") else instant,
                    reported_precision="unknown" if row.get("unknown_time") else "time",
                    published_at=instant,
                    summary_grounding={
                        "status": "review_limited" if item.get("paused") else "grounded",
                        "title_verified": not item.get("paused"),
                        "facts": [{"text": text, "quote": text} for text in item["facts"]],
                        "verification": {
                            "method": "source_entailment_review",
                            "model": "synthetic-fixture",
                        },
                    },
                )
                attach_reading(article)
                session.add(article)
        session.commit()
    print("Seeded 40 historical observations (withheld) and 8 synthetic scenarios")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", action="store_true", required=True)
    parser.parse_args()
    seed()
