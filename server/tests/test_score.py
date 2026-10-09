from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from unspun.core.models import Article, Event
from unspun.core.params import ScoringParams, load_scoring_params
from unspun.core.sources import Source
from unspun.pipeline.score import objective_score, score_event

CONFIG_DIR = Path(__file__).parents[2] / "config"


@pytest.fixture
def params() -> ScoringParams:
    return load_scoring_params(CONFIG_DIR)


# Minimal valid scoring.yml for pipeline-params tests; independent of the
# repo config so day-to-day tuning there never breaks the test suite.
BASE_SCORING_YAML = """\
final_score: {objective: 0.35, importance: 0.45, relevance: 0.20}
importance: {scope: 0.4, durability: 0.4, novelty: 0.2}
objective: {breadth: 0.40, growth: 0.25, source_quality: 0.25, community: 0.10}
clustering: {similarity_threshold: 0.72}
stream: {half_life_hours: 24}
offcircle_ratio: 0.20
"""


def write_scoring_yaml(tmp_path: Path, pipeline_section: str = "") -> Path:
    (tmp_path / "scoring.yml").write_text(BASE_SCORING_YAML + pipeline_section, encoding="utf-8")
    return tmp_path


def test_pipeline_params_are_config_driven(tmp_path: Path) -> None:
    write_scoring_yaml(
        tmp_path,
        "pipeline: {summary_batch_limit: 7, embed_batch_limit: 8,"
        " score_batch_limit: 9, max_summary_failures: 2}\n",
    )
    p = load_scoring_params(tmp_path).pipeline
    assert p.summary_batch_limit == 7
    assert p.embed_batch_limit == 8
    assert p.score_batch_limit == 9
    assert p.max_summary_failures == 2


def test_pipeline_params_default_when_section_missing(tmp_path: Path) -> None:
    write_scoring_yaml(tmp_path)
    p = load_scoring_params(tmp_path).pipeline
    assert p.summary_batch_limit == 50
    assert p.embed_batch_limit == 200
    assert p.score_batch_limit == 40
    assert p.max_summary_failures == 3


def test_pipeline_params_reject_non_positive_limits(tmp_path: Path) -> None:
    write_scoring_yaml(tmp_path, "pipeline: {summary_batch_limit: 0}\n")
    with pytest.raises(ValidationError):
        load_scoring_params(tmp_path)


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
