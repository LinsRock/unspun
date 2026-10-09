from pathlib import Path

from unspun.core.sources import load_sources

CONFIG_DIR = Path(__file__).parents[2] / "config"


def test_source_list_is_valid_and_in_m1_range() -> None:
    sources = load_sources(CONFIG_DIR)
    # M1 scope per docs/roadmaps.md: 20-30 sources.
    assert 20 <= len(sources) <= 30


def test_source_list_covers_both_languages() -> None:
    langs = {s.lang for s in load_sources(CONFIG_DIR)}
    assert langs == {"zh", "en"}


def test_weights_within_tier_bounds() -> None:
    for s in load_sources(CONFIG_DIR):
        assert 0.3 <= s.weight <= 1.0, s.id
