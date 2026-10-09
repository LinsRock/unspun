from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from unspun.core.models import Article, Event
from unspun.core.params import ScoringParams, load_scoring_params
from unspun.core.sources import Source
from unspun.pipeline.score import objective_score, score_event

CONFIG_DIR = Path(__file__).parents[2] / "config"


@pytest.fixture
def params() -> ScoringParams:
    return load_scoring_params(CONFIG_DIR)


def make_source(sid: str, lang: str, region: str, weight: float = 0.9) -> Source:
    return Source(
        id=sid,
        name=sid,
        url="https://example.com/feed",  # type: ignore[arg-type]  # pydantic coerces
        weight=weight,
        region=region,  # type: ignore[arg-type]
        kind="commercial",
        lang=lang,  # type: ignore[arg-type]
    )


def make_article(n: int, sid: str, hours_ago: float = 1.0) -> Article:
    return Article(
        source_id=sid,
        url=f"https://example.com/{n}",
        title=f"story {n}",
        fetched_at=datetime.now(UTC) - timedelta(hours=hours_ago),
        summary_zh="s",
        title_zh="t",
    )


def test_objective_score_rewards_breadth_and_recency(params: ScoringParams) -> None:
    sources = {
        "a": make_source("a", "en", "us"),
        "b": make_source("b", "zh", "cn-mainland"),
    }
    narrow, _ = objective_score([make_article(1, "a", hours_ago=48)], sources, params)
    broad, parts = objective_score(
        [make_article(1, "a"), make_article(2, "b"), make_article(3, "a")], sources, params
    )
    assert broad > narrow
    # Two sources, two languages, two regions: 40 + 10 + 10.
    assert parts["breadth"] == 60.0
    assert parts["growth"] == 60.0  # three articles inside the 24h window
    assert parts["community"] == 0.0


class FakeImportanceLlm:
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
        assert purpose == "importance"
        return {
            "scope": 4,
            "durability": 3,
            "novelty": 9,  # out of band on purpose; must clamp to 5
            "domain_importance": 4,
            "reason": "zh-reason",
            "confidence": "medium",
        }

    def embed(self, session: Session, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


def test_score_event_combines_components(db_session: Session, params: ScoringParams) -> None:
    sources = {"a": make_source("a", "en", "us"), "b": make_source("b", "zh", "eu")}
    event = Event()
    articles = [make_article(1, "a"), make_article(2, "b")]
    for a in articles:
        a.event = event
    db_session.add_all([event, *articles])
    db_session.flush()

    score_event(db_session, FakeImportanceLlm(), event, params, sources)

    assert event.scored_at is not None
    breakdown = event.score_breakdown
    assert breakdown is not None
    # 20 * (0.4*4 + 0.4*3 + 0.2*5) = 76
    assert breakdown["importance"]["score"] == pytest.approx(76.0)
    assert breakdown["importance"]["novelty"] == 5
    assert breakdown["importance"]["reason"] == "zh-reason"
    obj = breakdown["objective"]["score"]
    expected_final = (0.35 * obj + 0.45 * 76.0) / 0.80
    assert event.score_final == pytest.approx(expected_final)
