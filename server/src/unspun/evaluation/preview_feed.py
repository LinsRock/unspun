"""Fixed-clock B1 preview, explicitly restricted to a local preview database.

Seed once with ``python -m unspun.evaluation.preview_feed --seed``, then run
``uvicorn unspun.evaluation.preview_feed:app --host 127.0.0.1 --port 8013``.
No worker, network fetch or model call is started by this module.
"""

import argparse
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from unspun.core.config import get_settings
from unspun.core.db import get_engine
from unspun.core.models import Article, Event

DIRECTORY = Path(__file__).resolve().parents[4] / "docs/evaluations/m3b"
SNAPSHOT: dict[str, Any] = json.loads((DIRECTORY / "technical-candidates.json").read_text())
AS_OF = datetime.fromisoformat(SNAPSHOT["captured_at"])


def require_preview_database() -> None:
    url = make_url(get_settings().database_url)
    if url.host not in ("localhost", "127.0.0.1") or not str(url.database).startswith(
        "unspun_preview_"
    ):
        raise ValueError("preview requires a local unspun_preview_* database")


require_preview_database()

# Only this explicit preview entry point overrides the clock.
from unspun.api.app import app  # noqa: E402
from unspun.api.events import get_feed_now  # noqa: E402

app.dependency_overrides[get_feed_now] = lambda: AS_OF


def seed() -> None:
    require_preview_database()
    annotations = json.loads((DIRECTORY / "technical-annotations.json").read_text())
    groups = {
        int(article_id): group
        for label in annotations["labels"]
        for article_id, group in label["article_publisher_groups"].items()
    }
    synthetic = json.loads((DIRECTORY / "preview-cases.json").read_text())
    with Session(get_engine()) as session:
        if session.scalar(select(func.count()).select_from(Event)) or session.scalar(
            select(func.count()).select_from(Article)
        ):
            raise ValueError("preview seeding requires an empty preview database")
        for row in [*SNAPSHOT["events"], *synthetic["events"]]:
            impact = None
            if "public_impact_status" in row:
                impact = {
                    "status": row["public_impact_status"],
                    "is_urgent": row["public_impact_urgent"],
                    "evidence": row["public_impact_evidence"],
                    "assessed_at": row["public_impact_assessed_at"],
                    "model": row["public_impact_model"],
                    "input_fingerprint": row["public_impact_input_fingerprint"],
                    "reason": row["public_impact_reason"],
                }
            event = Event(
                id=row["id"],
                title=row["title"],
                summary_zh=row.get("summary_zh"),
                score_final=row["score_final"],
                score_breakdown=row.get("score_breakdown"),
                first_seen_at=datetime.fromisoformat(row["first_seen_at"]),
                changed_at=datetime.fromisoformat(row["changed_at"]),
                scored_at=AS_OF,
                public_impact=impact,
            )
            session.add(event)
            for article in row["articles"]:
                session.add(
                    Article(
                        id=article["id"],
                        event=event,
                        source_id=article["source_id"],
                        url=article["url"],
                        title=article["title"],
                        content=article.get("impact_original_excerpt") or article.get("content"),
                        content_basis="original"
                        if article.get("impact_original_excerpt")
                        else article.get("content_basis", "unknown"),
                        lang="zh",
                        published_at=datetime.fromisoformat(article["published_at"])
                        if article["published_at"]
                        else None,
                        fetched_at=datetime.fromisoformat(article["fetched_at"]),
                        reported_at=datetime.fromisoformat(article["reported_at"])
                        if article["reported_at"]
                        else None,
                        reported_date=date.fromisoformat(article["reported_date"])
                        if article["reported_date"]
                        else None,
                        reported_precision=article["reported_precision"],
                        reported_basis=article["reported_basis"],
                        publisher_group=groups.get(article["id"], article.get("publisher_group")),
                    )
                )
        session.commit()
    print(
        f"Seeded {len(SNAPSHOT['events'])} real snapshots "
        f"and {len(synthetic['events'])} synthetic events"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", action="store_true", required=True)
    parser.parse_args()
    seed()
