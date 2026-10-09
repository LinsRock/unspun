from pathlib import Path

from unspun.core.sources import load_sources, resolve_rsshub_url

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


def test_rsshub_sources_resolve_against_configured_base() -> None:
    by_id = {s.id: s for s in load_sources(CONFIG_DIR)}
    caixin = by_id["caixin"]
    # Default settings: rsshub_url = http://rsshub:1200.
    assert str(caixin.url) == "http://rsshub:1200/caixin/latest"
    assert caixin.timeout_seconds == 60
