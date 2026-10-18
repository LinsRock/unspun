import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from unspun.core.sources import Source, load_sources, resolve_rsshub_url

CONFIG_DIR = Path(__file__).parents[2] / "config"


def test_source_list_is_valid_and_in_m2_range() -> None:
    sources = load_sources(CONFIG_DIR)
    # M2 scope per docs/roadmaps.md: growing toward ~100 sources.
    assert 20 <= len(sources) <= 110


def test_source_list_covers_both_languages() -> None:
    langs = {s.lang for s in load_sources(CONFIG_DIR)}
    assert langs == {"zh", "en"}


def test_weights_within_tier_bounds() -> None:
    for s in load_sources(CONFIG_DIR):
        assert 0.3 <= s.weight <= 1.0, s.id


def test_resolve_rsshub_url_expands_routes() -> None:
    assert (
        resolve_rsshub_url("rsshub://caixin/latest", "http://rsshub:1200")
        == "http://rsshub:1200/caixin/latest"
    )
    # Trailing slash on the base must not produce a double slash.
    assert (
        resolve_rsshub_url("rsshub://36kr/newsflashes", "http://localhost:1200/")
        == "http://localhost:1200/36kr/newsflashes"
    )
    # Plain http(s) URLs pass through untouched.
    assert resolve_rsshub_url("https://example.com/feed", "http://rsshub:1200") == (
        "https://example.com/feed"
    )


def test_rsshub_sources_resolve_against_explicit_base() -> None:
    by_id = {s.id: s for s in load_sources(CONFIG_DIR, rsshub_base="http://rsshub-test:1200")}
    caixin = by_id["caixin"]
    assert str(caixin.url) == "http://rsshub-test:1200/caixin/latest"
    assert caixin.timeout_seconds == 60


def test_timeout_seconds_must_be_positive() -> None:
    fields = {
        "id": "x",
        "name": "X",
        "url": "https://example.com/feed",
        "weight": 0.5,
        "region": "us",
        "kind": "commercial",
        "lang": "en",
    }
    with pytest.raises(ValidationError):
        Source.model_validate({**fields, "timeout_seconds": 0})
    assert Source.model_validate({**fields, "timeout_seconds": 60}).timeout_seconds == 60


def test_runtime_matches_registered_rollout_and_material_boundaries() -> None:
    registration = json.loads(
        (CONFIG_DIR.parent / "docs/evaluations/r1/production-rollout-v2.json").read_text()
    )
    sources = load_sources(CONFIG_DIR)
    registered = set(registration["source_ids"])
    suspended = {row["source_id"] for row in registration.get("runtime_suspensions", [])}
    assert suspended <= registered
    approved = registered - suspended
    for stage in ("discovery", "material", "paid", "publish"):
        assert {s.id for s in sources if s.r1 and getattr(s.r1, stage)} == approved
    for source in sources:
        if source.id in suspended:
            assert source.r1 is not None
            assert not source.legacy_enabled and source.discovery_owner == "r1"
            assert not any(
                getattr(source.r1, stage) for stage in ("discovery", "material", "paid", "publish")
            )
            assert not source.r1.paid_scopes and not source.r1.publish_scopes
        if source.id not in approved:
            continue
        assert source.r1 is not None
        assert not source.legacy_enabled and source.discovery_owner == "r1"
        assert source.max_items == registration["per_source_bounds"][source.id]["max_items"]
        assert (
            source.r1.period_seconds
            == registration["per_source_bounds"][source.id]["period_seconds"]
        )
        assert source.r1.paid_scopes and source.r1.publish_scopes
        assert source.r1.paid_scopes == source.r1.publish_scopes
        if source.id == "bbc-world":
            assert source.r1.paid_scopes == ("media_description",)
        if source.id in {"nyt-world", "wsj-world"}:
            assert source.r1.paid_scopes == ("preview",)
    xinhua = next(s for s in sources if s.id == "xinhua")
    assert xinhua.r1 and not xinhua.r1.paid and not xinhua.r1.publish
