from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from tests.billing_fakes import RecordingJournal
from tests.reading_fixtures import approve_event
from unspun.core import db
from unspun.core.llm import LlmClient, LlmError
from unspun.core.models import Digest, Event, EventViewpoint, LlmUsage
from unspun.core.params import DigestParams, load_scoring_params
from unspun.pipeline import digest as digest_module
from unspun.pipeline.digest import (
    digest_pending,
    due_report_date,
    generate_digest,
    select_digest_events,
)

NOW = datetime(2030, 10, 10, 4, tzinfo=UTC)
PARAMS = DigestParams()


class FakeDigestLlm:
    def __init__(self, response: dict[str, Any] | None = None, fail: bool = False) -> None:
        self.calls = 0
        self.response = (
            response if response is not None else {"intro": "\u6bcf\u65e5\u4e8b\u4ef6\u5bfc\u8bfb"}
        )
        self.fail = fail

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
        assert purpose == "digest"
        assert model
        self.calls += 1
        session.add(LlmUsage(purpose=purpose, model=model, cost_usd=0.002))
        if self.fail:
            raise LlmError("bad JSON")
        return self.response

    def embed(self, session: Session, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


def seed(session: Session, title: str, hours: float, score: float | None = 50) -> Event:
    event = Event(
        title=title,
        summary_zh="summary",
        score_final=score,
        changed_at=NOW - timedelta(hours=hours),
        first_seen_at=NOW - timedelta(days=3),
    )
    session.add(event)
    session.flush()
    approve_event(event)
    session.flush()
    return event


@pytest.mark.parametrize(
    "value",
    [{"digest_hour": -1}, {"digest_hour": 24}, {"top_n": 0}, {"digest_timezone": "not/a-zone"}],
)
def test_digest_config_rejects_invalid_values(value: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        DigestParams.model_validate(value)


def test_schedule_timezone_boundary_and_catchup() -> None:
    assert due_report_date(datetime(2030, 10, 9, 23, 59, tzinfo=UTC), PARAMS) is None
    assert due_report_date(datetime(2030, 10, 10, 0, tzinfo=UTC), PARAMS) == date(2030, 10, 10)
    assert due_report_date(NOW, PARAMS) == date(2030, 10, 10)
    assert due_report_date(datetime(2030, 10, 10, 16, tzinfo=UTC), PARAMS) is None
    assert due_report_date(datetime(2030, 10, 11, 0, tzinfo=UTC), PARAMS) == date(2030, 10, 11)
    utc = DigestParams(digest_timezone="UTC")
    assert due_report_date(NOW, utc) is None


def test_selection_is_windowed_decayed_top_n(db_session: Session) -> None:
    fresh = seed(db_session, "fresh", 0, 60)
    boundary = seed(db_session, "boundary", 24, 100)  # decayed to 50
    seed(db_session, "too old", 24.001, 100)
    seed(db_session, "future", -0.001, 100)
    seed(db_session, "unscored", 0, None)
    missing = seed(db_session, "no summary", 0, 100)
    missing.summary_zh = None
    seed(db_session, "low", 1, 10)
    rows = select_digest_events(db_session, NOW, top_n=2, half_life_hours=24)
    assert [event.id for event, _ in rows] == [fresh.id, boundary.id]
    assert [score for _, score in rows] == pytest.approx([60, 50])


def test_generation_stores_snapshot_and_replaces_same_day(db_session: Session) -> None:
    event = seed(db_session, "original", 1, 80)
    article = event.articles[0]
    db_session.flush()
    event.viewpoint = EventViewpoint(
        payload={
            "claims": [
                {"article_id": article.id, "claim": "\u6709\u4f9d\u636e\u7684\u8bf4\u6cd5"},
                {"article_id": 999999, "claim": "foreign"},
            ],
            "disagreements": [],
        },
        input_fingerprint="f",
        model="viewpoint-model",
        generated_at=NOW,
    )
    db_session.flush()
    client = FakeDigestLlm()
    assert generate_digest(db_session, client, date(2030, 10, 10), NOW, PARAMS, 24)
    row = db_session.scalar(select(Digest).where(Digest.report_date == date(2030, 10, 10)))
    assert row is not None
    snapshot = row.payload
    assert snapshot["intro"] == "\u6bcf\u65e5\u4e8b\u4ef6\u5bfc\u8bfb"
    assert snapshot["events"][0]["articles"][0]["source_name"] == "BBC World"
    assert snapshot["events"][0]["viewpoint"]["claims"] == [
        {
            "article_id": article.id,
            "claim": "\u6709\u4f9d\u636e\u7684\u8bf4\u6cd5",
            "evidence_quote": None,
        }
    ]
    event.title = "updated"
    db_session.flush()
    assert row.payload["events"][0]["title"] == article.title_zh
    assert generate_digest(db_session, client, date(2030, 10, 10), NOW, PARAMS, 24)
    db_session.flush()
    assert row.payload["events"][0]["title"] == article.title_zh
    assert (
        db_session.scalar(
            select(func.count()).select_from(Digest).where(Digest.report_date == date(2030, 10, 10))
        )
        == 1
    )


def test_empty_digest_does_not_call_llm(db_session: Session) -> None:
    client = FakeDigestLlm()
    later = NOW + timedelta(days=100)
    assert generate_digest(db_session, client, later.date(), later, PARAMS, 24)
    assert client.calls == 0
    row = db_session.scalar(select(Digest).where(Digest.report_date == later.date()))
    assert row is not None and row.payload["events"] == [] and row.payload["intro"]


@pytest.mark.parametrize("response", [{"intro": ""}, {"intro": 123}, {}, {"intro": "   "}])
def test_bad_intro_preserves_existing_digest_and_usage(
    db_session: Session,
    response: dict[str, Any],
) -> None:
    seed(db_session, "bad intro", 0)
    row = Digest(report_date=NOW.date(), payload={"intro": "existing"}, generated_at=NOW)
    db_session.add(row)
    db_session.flush()
    before = db_session.scalar(select(func.count()).select_from(LlmUsage)) or 0
    assert not generate_digest(db_session, FakeDigestLlm(response), NOW.date(), NOW, PARAMS, 24)
    db_session.flush()
    assert row.payload == {"intro": "existing"}
    assert db_session.scalar(select(func.count()).select_from(LlmUsage)) == before + 1


def test_llm_failure_leaves_no_digest_and_keeps_usage(db_session: Session) -> None:
    seed(db_session, "failed", 0)
    before = db_session.scalar(select(func.count()).select_from(LlmUsage)) or 0
    assert not generate_digest(db_session, FakeDigestLlm(fail=True), NOW.date(), NOW, PARAMS, 24)
    db_session.flush()
    assert db_session.scalar(select(Digest).where(Digest.report_date == NOW.date())) is None
    assert db_session.scalar(select(func.count()).select_from(LlmUsage)) == before + 1


def test_repo_digest_config() -> None:
    params = load_scoring_params(Path(__file__).parents[2] / "config").digest
    assert params.digest_hour == 8
    assert params.digest_timezone == "Asia/Shanghai"
    assert params.top_n == 10


def test_default_selects_ten_hottest_not_ten_latest(db_session: Session) -> None:
    events = [seed(db_session, f"rank {n}", 1, n) for n in range(1, 13)]
    latest = seed(db_session, "latest but cold", 0, 0)
    rows = select_digest_events(db_session, NOW, top_n=PARAMS.top_n, half_life_hours=24)
    assert [e.id for e, _ in rows] == [e.id for e in reversed(events[2:])]
    assert latest.id not in {e.id for e, _ in rows}


def test_scheduler_catchup_skips_same_day_and_generates_next_day(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @contextmanager
    def scope() -> Generator[Session]:
        yield db_session
        db_session.flush()

    monkeypatch.setattr(digest_module, "session_scope", scope)
    # No key is needed for empty daily snapshots, and no real LLM is called.
    monkeypatch.setattr(digest_module.get_settings(), "openrouter_api_key", "")
    later = NOW + timedelta(days=200)
    before = later.replace(hour=23, minute=59) - timedelta(days=1)
    assert not digest_pending(before)
    assert digest_pending(later)
    assert not digest_pending(later + timedelta(hours=1))
    assert digest_pending(later + timedelta(days=1))


def test_no_key_with_events_leaves_digest_pending(db_session: Session) -> None:
    seed(db_session, "needs intro", 0)
    assert not generate_digest(db_session, None, NOW.date(), NOW, PARAMS, 24)
    assert db_session.scalar(select(Digest).where(Digest.report_date == NOW.date())) is None


def test_scheduler_commits_usage_after_failure_and_retries_next_cycle(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed(db_session, "retry", 0)
    # Real session_scope commits into savepoints; the fixture's outer
    # transaction still rolls all test data back afterwards.
    monkeypatch.setattr(
        db,
        "_session_factory",
        sessionmaker(
            bind=db_session.connection(),
            join_transaction_mode="create_savepoint",
        ),
    )
    monkeypatch.setattr(digest_module.get_settings(), "openrouter_api_key", "test-only")
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        content = (
            "not JSON" if calls == 1 else '{"intro": "\u91cd\u8bd5\u540e\u751f\u6210\u65e5\u62a5"}'
        )
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.001},
            },
        )

    monkeypatch.setattr(
        digest_module,
        "LlmClient",
        lambda: LlmClient(
            transport=httpx.MockTransport(handler),
            journal_factory=RecordingJournal,
        ),
    )
    with db.session_scope() as session:
        before = session.scalar(select(func.count()).select_from(LlmUsage)) or 0
    assert not digest_pending(NOW)
    with db.session_scope() as session:
        assert session.scalar(select(Digest).where(Digest.report_date == NOW.date())) is None
        assert session.scalar(select(func.count()).select_from(LlmUsage)) == before + 1
    assert digest_pending(NOW + timedelta(minutes=30))
    with db.session_scope() as session:
        row = session.scalar(select(Digest).where(Digest.report_date == NOW.date()))
        assert (
            row is not None and row.payload["intro"] == "\u91cd\u8bd5\u540e\u751f\u6210\u65e5\u62a5"
        )
        assert session.scalar(select(func.count()).select_from(LlmUsage)) == before + 2
    assert not digest_pending(NOW + timedelta(hours=1))
    assert calls == 2
