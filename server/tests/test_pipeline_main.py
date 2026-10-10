import pytest

from unspun.pipeline import main


def test_cycle_checks_digest_before_other_stages(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(main, "digest_pending", lambda: calls.append("digest"))
    monkeypatch.setattr(main, "run_fetch_cycle", lambda: calls.append("fetch"))
    monkeypatch.setattr(main, "run_ai_stages", lambda: calls.append("ai"))
    main.run_cycle()
    assert calls == ["digest", "fetch", "ai"]


def test_digest_failure_does_not_block_regular_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fail() -> None:
        raise RuntimeError("digest failed")

    monkeypatch.setattr(main, "digest_pending", fail)
    monkeypatch.setattr(main, "run_fetch_cycle", lambda: calls.append("fetch"))
    monkeypatch.setattr(main, "run_ai_stages", lambda: calls.append("ai"))
    main.run_cycle()
    assert calls == ["fetch", "ai"]
