import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from unspun.core.llm import LlmError
from unspun.core.models import Article, Event, EventViewpoint, LlmUsage
from unspun.core.params import ViewpointsParams, load_scoring_params
from unspun.core.sources import Source
from unspun.pipeline.viewpoints import (
    candidate_viewpoint_ids,
    input_fingerprint,
    is_eligible,
    parse_viewpoints_payload,
    prompt_articles,
    refresh_event_viewpoint,
)

CONFIG_DIR = Path(__file__).parents[2] / "config"

# Independent of the repo config so tuning there never breaks the suite.
BASE_SCORING_YAML = """\
final_score: {objective: 0.35, importance: 0.45, relevance: 0.20}
importance: {scope: 0.4, durability: 0.4, novelty: 0.2}
objective: {breadth: 0.40, growth: 0.25, source_quality: 0.25, community: 0.10}
clustering: {similarity_threshold: 0.72}
stream: {half_life_hours: 24}
offcircle_ratio: 0.20
"""


def make_source(sid: str, region: str = "us", kind: str = "commercial") -> Source:
    return Source(
        id=sid,
        name=f"name-{sid}",
        url="https://example.com/feed",  # type: ignore[arg-type]  # pydantic coerces
        weight=0.9,
        region=region,  # type: ignore[arg-type]
        kind=kind,  # type: ignore[arg-type]
        lang="en",
    )


def make_article(n: int, sid: str) -> Article:
    return Article(
        source_id=sid,
        url=f"https://example.com/{n}",
        title=f"story {n}",
        title_zh=f"t{n}",
        summary_zh=f"s{n}",
        content=f"Original coverage for story {n}.",
    )


PARAMS = ViewpointsParams()


# --- config ---


def test_viewpoints_params_are_config_driven(tmp_path: Path) -> None:
    (tmp_path / "scoring.yml").write_text(
        BASE_SCORING_YAML
        + "viewpoints: {min_sources: 4, min_regions: 3, min_kinds: 3, viewpoint_batch_limit: 5}\n",
        encoding="utf-8",
    )
    v = load_scoring_params(tmp_path).viewpoints
    assert v.min_sources == 4
    assert v.min_regions == 3
    assert v.min_kinds == 3
    assert v.viewpoint_batch_limit == 5


def test_viewpoints_params_default_when_section_missing(tmp_path: Path) -> None:
    (tmp_path / "scoring.yml").write_text(BASE_SCORING_YAML, encoding="utf-8")
    v = load_scoring_params(tmp_path).viewpoints
    assert v.min_sources == 3
    assert v.min_regions == 2
    assert v.min_kinds == 2
    assert v.viewpoint_batch_limit == 10


def test_viewpoints_params_reject_degenerate_gate(tmp_path: Path) -> None:
    (tmp_path / "scoring.yml").write_text(
        BASE_SCORING_YAML + "viewpoints: {min_sources: 1}\n", encoding="utf-8"
    )
    with pytest.raises(ValidationError):
        load_scoring_params(tmp_path)


def test_repo_config_parses() -> None:
    load_scoring_params(CONFIG_DIR)


# --- eligibility gate ---


def test_gate_rejects_too_few_sources() -> None:
    sources = {"a": make_source("a", "us"), "b": make_source("b", "eu")}
    articles = [make_article(1, "a"), make_article(2, "b"), make_article(3, "a")]
    assert not is_eligible(articles, sources, PARAMS)


def test_gate_rejects_monoculture() -> None:
    # Three sources, but one region and one kind: no contrast to compare.
    sources = {f"s{i}": make_source(f"s{i}", "us", "commercial") for i in range(3)}
    articles = [make_article(i, f"s{i}") for i in range(3)]
    assert not is_eligible(articles, sources, PARAMS)


def test_gate_accepts_region_diversity() -> None:
    sources = {
        "a": make_source("a", "us", "commercial"),
        "b": make_source("b", "cn-mainland", "commercial"),
        "c": make_source("c", "us", "commercial"),
    }
    articles = [make_article(i, sid) for i, sid in enumerate(["a", "b", "c"])]
    assert is_eligible(articles, sources, PARAMS)


def test_gate_accepts_kind_diversity() -> None:
    sources = {
        "a": make_source("a", "us", "wire"),
        "b": make_source("b", "us", "state"),
        "c": make_source("c", "us", "wire"),
    }
    articles = [make_article(i, sid) for i, sid in enumerate(["a", "b", "c"])]
    assert is_eligible(articles, sources, PARAMS)


def test_gate_unknown_sources_count_but_prove_no_diversity() -> None:
    # Two unknown sources + one known: three independent sources, but only
    # the known one has a region/kind, so diversity is unproven.
    sources = {"a": make_source("a", "us")}
    articles = [make_article(i, sid) for i, sid in enumerate(["a", "x", "y"])]
    assert not is_eligible(articles, sources, PARAMS)


# --- fingerprint ---


def test_fingerprint_is_order_independent() -> None:
    assert input_fingerprint([3, 1, 2]) == input_fingerprint([1, 2, 3])
    assert input_fingerprint([1, 2]) != input_fingerprint([1, 2, 3])


# --- prompt selection ---


def test_prompt_articles_latest_per_source_weighted_order() -> None:
    heavy = make_source("heavy", "us")
    light = make_source("light", "eu")
    light.weight = 0.3
    sources = {"heavy": heavy, "light": light}
    old = make_article(1, "light")
    new = make_article(2, "light")
    old.id, new.id = 1, 2
    now = datetime.now(UTC)
    old.published_at = now - timedelta(hours=5)
    new.published_at = now - timedelta(hours=1)
    other = make_article(3, "heavy")
    other.id = 3
    selected = prompt_articles([old, new, other], sources)
    assert [a.id for a in selected] == [3, 2]


# --- output validation ---


def test_parse_drops_untraceable_claims_and_remaps_indexes() -> None:
    out: dict[str, Any] = {
        "claims": [
            {"article_id": 10, "claim": "a"},
            {"article_id": 99, "claim": "hallucinated id"},
            {"article_id": 11, "claim": "b"},
        ],
        "disagreements": [
            {"point": "p", "claim_indexes": [0, 1, 2]},
            {"point": "only one side left", "claim_indexes": [1, 2]},
        ],
    }
    payload = parse_viewpoints_payload(out, {10, 11})
    assert [c["article_id"] for c in payload["claims"]] == [10, 11]
    # Index 1 (dropped claim) vanishes; index 2 remaps to 1.
    assert payload["disagreements"] == [{"point": "p", "claim_indexes": [0, 1]}]


def test_parse_keeps_first_claim_per_article() -> None:
    out: dict[str, Any] = {
        "claims": [
            {"article_id": 10, "claim": "first"},
            {"article_id": 10, "claim": "repeat"},
            {"article_id": 11, "claim": "b"},
        ],
        "disagreements": [{"point": "p", "claim_indexes": [1, 2]}],
    }
    payload = parse_viewpoints_payload(out, {10, 11})
    assert payload["claims"] == [
        {"article_id": 10, "claim": "first"},
        {"article_id": 11, "claim": "b"},
    ]
    # The duplicate's index is gone, leaving the point with one side.
    assert payload["disagreements"] == []


def test_parse_rejects_duplicates_masquerading_as_two_claims() -> None:
    out: dict[str, Any] = {
        "claims": [{"article_id": 1, "claim": "x"}, {"article_id": 1, "claim": "y"}],
        "disagreements": [],
    }
    with pytest.raises(LlmError):
        parse_viewpoints_payload(out, {1, 2})


def test_parse_rejects_missing_or_insufficient_claims() -> None:
    with pytest.raises(LlmError):
        parse_viewpoints_payload({"disagreements": []}, {1})
    with pytest.raises(LlmError):
        parse_viewpoints_payload({"claims": [{"article_id": 1, "claim": "x"}]}, {1, 2})


def test_parse_tolerates_malformed_disagreements() -> None:
    out: dict[str, Any] = {
        "claims": [{"article_id": 1, "claim": "a"}, {"article_id": 2, "claim": "b"}],
        "disagreements": ["not a dict", {"point": "", "claim_indexes": [0, 1]}, {"point": "ok"}],
    }
    payload = parse_viewpoints_payload(out, {1, 2})
    assert payload["disagreements"] == []


# --- refresh on the database ---


class FakeViewpointLlm:
    def __init__(
        self, response: dict[str, Any] | None = None, review_response: dict[str, Any] | None = None
    ) -> None:
        self.calls = 0
        self.response = response
        self.review_response = review_response

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
        assert purpose in {"viewpoint", "grounding"}
        self.calls += 1
        session.add(LlmUsage(purpose=purpose, model=model, prompt_tokens=10, cost_usd=0.001))
        if purpose == "grounding":
            return (
                self.review_response
                if self.review_response is not None
                else json.loads(user)["draft"]
            )
        if self.response is not None:
            return self.response
        # Claims for the article_ids present in the prompt.
        rows = json.loads(user)["articles"]
        return {
            "claims": [
                {
                    "article_id": row["article_id"],
                    "claim": "\u6765\u6e90\u62a5\u9053\u4e8b\u4ef6",
                    "evidence_quote": row["original_evidence"],
                }
                for row in rows
            ],
            "disagreements": [
                {"point": "framing differs", "claim_indexes": [0, 1], "kind": "coverage_difference"}
            ],
        }

    def embed(self, session: Session, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


def seed_event(session: Session, source_ids: list[str]) -> Event:
    event = Event()
    articles = [make_article(i, sid) for i, sid in enumerate(source_ids)]
    for a in articles:
        a.event = event
        a.url = f"https://example.com/{id(a)}"  # unique across tests
    session.add_all([event, *articles])
    session.flush()
    return event


DIVERSE_SOURCES = {
    "a": make_source("a", "us"),
    "b": make_source("b", "cn-mainland"),
    "c": make_source("c", "eu"),
}


def test_refresh_generates_and_skips_unchanged(db_session: Session) -> None:
    event = seed_event(db_session, ["a", "b", "c"])
    llm = FakeViewpointLlm()

    assert refresh_event_viewpoint(db_session, llm, event, PARAMS, DIVERSE_SOURCES) == "generated"
    db_session.flush()
    viewpoint = event.viewpoint
    assert viewpoint is not None
    article_ids = {a.id for a in event.articles}
    assert {c["article_id"] for c in viewpoint.payload["claims"]} <= article_ids
    assert viewpoint.input_fingerprint == input_fingerprint(
        list(event.articles), DIVERSE_SOURCES, viewpoint.model
    )

    # Same article set: no second LLM call.
    assert refresh_event_viewpoint(db_session, llm, event, PARAMS, DIVERSE_SOURCES) == "skipped"
    assert llm.calls == 2


def test_refresh_skips_ineligible_without_llm_call(db_session: Session) -> None:
    event = seed_event(db_session, ["a", "a", "b"])  # two sources only
    llm = FakeViewpointLlm()
    assert refresh_event_viewpoint(db_session, llm, event, PARAMS, DIVERSE_SOURCES) == "skipped"
    assert llm.calls == 0
    assert event.viewpoint is None


def test_refresh_replaces_row_when_articles_change(db_session: Session) -> None:
    event = seed_event(db_session, ["a", "b", "c"])
    llm = FakeViewpointLlm()
    assert refresh_event_viewpoint(db_session, llm, event, PARAMS, DIVERSE_SOURCES) == "generated"
    db_session.flush()
    assert event.viewpoint is not None
    row_id = event.viewpoint.id
    first_fingerprint = event.viewpoint.input_fingerprint

    extra = make_article(99, "a")
    extra.url = "https://example.com/extra"
    extra.event = event
    db_session.add(extra)
    db_session.flush()
    db_session.refresh(event)

    assert refresh_event_viewpoint(db_session, llm, event, PARAMS, DIVERSE_SOURCES) == "generated"
    db_session.flush()
    assert llm.calls == 4
    assert event.viewpoint is not None
    assert event.viewpoint.id == row_id  # replaced in place, one row per event
    assert event.viewpoint.input_fingerprint != first_fingerprint


def test_refresh_rejects_unusable_output_but_keeps_usage(db_session: Session) -> None:
    event = seed_event(db_session, ["a", "b", "c"])
    llm = FakeViewpointLlm(response={"claims": "not a list"})
    # No raise: raising would roll back the LlmUsage row chat_json recorded,
    # hiding real spend from the cost report (D-007).
    assert refresh_event_viewpoint(db_session, llm, event, PARAMS, DIVERSE_SOURCES) == "rejected"
    db_session.flush()
    assert event.viewpoint is None
    usage = db_session.scalars(select(LlmUsage).where(LlmUsage.purpose == "viewpoint")).all()
    assert len(usage) == 1


# --- candidate query ---


def test_candidate_query_filters_by_sources_and_staleness(db_session: Session) -> None:
    diverse = seed_event(db_session, ["a", "b", "c"])
    narrow = seed_event(db_session, ["a", "a", "b"])
    done = seed_event(db_session, ["a", "b", "c"])
    done.viewpoint = EventViewpoint(payload={}, input_fingerprint="f", model="m")
    db_session.flush()
    # done's viewpoint is fresh (generated_at defaults to now > changed_at).
    db_session.refresh(done)

    ids = candidate_viewpoint_ids(db_session, min_sources=3)
    assert diverse.id in ids
    assert narrow.id not in ids
    assert done.id in ids  # Legacy/changed content requires Python fingerprint examination.
