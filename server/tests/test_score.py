import math
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


@pytest.fixture
def pinned_params(tmp_path: Path) -> ScoringParams:
    """Params with pinned objective_signals, so repo-config tuning never
    changes what the objective-score tests assert."""
    write_scoring_yaml(
        tmp_path,
        "objective_signals: {source_cap: 15, recent_cap: 10,"
        " monolocal_discount: 0.7, growth_window_hours: 24}\n",
    )
    return load_scoring_params(tmp_path)


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


def test_objective_signals_are_config_driven(tmp_path: Path) -> None:
    write_scoring_yaml(
        tmp_path,
        "objective_signals: {source_cap: 20, recent_cap: 6,"
        " monolocal_discount: 0.5, growth_window_hours: 12}\n",
    )
    o = load_scoring_params(tmp_path).objective_signals
    assert o.source_cap == 20
    assert o.recent_cap == 6
    assert o.monolocal_discount == 0.5
    assert o.growth_window_hours == 12


def test_objective_signals_default_when_section_missing(tmp_path: Path) -> None:
    write_scoring_yaml(tmp_path)
    o = load_scoring_params(tmp_path).objective_signals
    assert o.source_cap == 15
    assert o.recent_cap == 10
    assert o.monolocal_discount == 0.7
    assert o.growth_window_hours == 24


def test_objective_signals_reject_out_of_range_discount(tmp_path: Path) -> None:
    write_scoring_yaml(tmp_path, "objective_signals: {monolocal_discount: 0}\n")
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


def make_article(
    n: int, sid: str, hours_ago: float = 1.0, published_hours_ago: float | None = None
) -> Article:
    now = datetime.now(UTC)
    return Article(
        source_id=sid,
        url=f"https://example.com/{n}",
        title=f"story {n}",
        fetched_at=now - timedelta(hours=hours_ago),
        published_at=(
            now - timedelta(hours=published_hours_ago) if published_hours_ago is not None else None
        ),
        summary_zh="s",
        title_zh="t",
    )


def expected_log_score(count: int, cap: int) -> float:
    return 100.0 * math.log1p(count) / math.log1p(cap)


def test_objective_score_rewards_breadth_and_recency(pinned_params: ScoringParams) -> None:
    cfg = pinned_params.objective_signals
    sources = {
        "a": make_source("a", "en", "us"),
        "b": make_source("b", "zh", "cn-mainland"),
    }
    narrow, _ = objective_score([make_article(1, "a", hours_ago=48)], sources, pinned_params)
    broad, parts = objective_score(
        [make_article(1, "a"), make_article(2, "b"), make_article(3, "a")], sources, pinned_params
    )
    assert broad > narrow
    # Two sources across two languages/regions: no monolocal discount.
    assert parts["breadth"] == pytest.approx(expected_log_score(2, cfg.source_cap))
    # Three articles inside the growth window (fetched_at fallback).
    assert parts["growth"] == pytest.approx(expected_log_score(3, cfg.recent_cap))
    assert parts["community"] == 0.0


def test_objective_score_discounts_monolocal_pileups(pinned_params: ScoringParams) -> None:
    local = {f"s{i}": make_source(f"s{i}", "zh", "cn-mainland") for i in range(5)}
    articles = [make_article(i, f"s{i}") for i in range(5)]
    _, local_parts = objective_score(articles, local, pinned_params)
    # Hard-pinned acceptance number (A10): 5 monolocal sources score ~45,
    # not 100 — 100*ln(6)/ln(16)*0.7. Independent of the implementation's
    # own formula, so a shared-formula bug cannot hide here.
    assert local_parts["breadth"] == pytest.approx(45.23, abs=0.05)

    # Same source count, but spanning languages and regions: no discount,
    # so the local pileup scores strictly lower.
    mixed = {
        "s0": make_source("s0", "zh", "cn-mainland"),
        "s1": make_source("s1", "en", "us"),
        "s2": make_source("s2", "en", "eu"),
        "s3": make_source("s3", "zh", "cn-mainland"),
        "s4": make_source("s4", "en", "us"),
    }
    _, mixed_parts = objective_score(articles, mixed, pinned_params)
    assert mixed_parts["breadth"] == pytest.approx(64.62, abs=0.05)
    assert local_parts["breadth"] < mixed_parts["breadth"]


def test_objective_score_no_discount_for_unknown_sources(pinned_params: ScoringParams) -> None:
    cfg = pinned_params.objective_signals
    # Three counted sources but only one matches config (e.g. after a
    # rename in sources.yml): missing sources are not evidence of
    # monolocality, so the discount must not fire.
    sources = {"s0": make_source("s0", "zh", "cn-mainland")}
    articles = [make_article(i, f"s{i}") for i in range(3)]
    _, parts = objective_score(articles, sources, pinned_params)
    assert parts["breadth"] == pytest.approx(expected_log_score(3, cfg.source_cap))


def test_objective_score_saturates_at_source_cap(pinned_params: ScoringParams) -> None:
    n = pinned_params.objective_signals.source_cap
    sources = {
        f"s{i}": make_source(f"s{i}", "en" if i % 2 else "zh", "us" if i % 2 else "eu")
        for i in range(n)
    }
    articles = [make_article(i, f"s{i}") for i in range(n)]
    _, parts = objective_score(articles, sources, pinned_params)
    assert parts["breadth"] == pytest.approx(100.0)


def test_objective_score_growth_ignores_backfilled_and_future(
    pinned_params: ScoringParams,
) -> None:
    sources = {"a": make_source("a", "en", "us"), "b": make_source("b", "zh", "eu")}
    # Published long ago but fetched just now (a backfill), or carrying a
    # future timestamp from a broken feed clock: neither is growth.
    articles = [
        make_article(1, "a", hours_ago=0.5, published_hours_ago=72),
        make_article(2, "b", hours_ago=0.5, published_hours_ago=200),
        make_article(3, "a", hours_ago=0.5, published_hours_ago=-48),
    ]
    _, parts = objective_score(articles, sources, pinned_params)
    assert parts["growth"] == 0.0


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
