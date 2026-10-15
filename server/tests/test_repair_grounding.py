import json
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from unspun.core.models import EMBEDDING_DIM, Article, Digest, Event, LlmUsage
from unspun.pipeline.repair_grounding import repair_event


class RepairLlm:
    def __init__(self, fail_embedding: bool = False) -> None:
        self.calls = 0
        self.fail_embedding = fail_embedding
        self.last_viewpoint: dict[str, Any] = {}

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
        self.calls += 1
        session.add(LlmUsage(purpose=purpose, model=model, cost_usd=0.001))
        if purpose == "summary":
            return {
                "title_zh": "\u6865\u6881\u6062\u590d\u5f00\u653e",
                "facts": [
                    {
                        "text": "\u6865\u6881\u4e8e11:00\u6062\u590d\u5f00\u653e\u3002",
                        "quote": "The bridge reopened at 11:00.",
                    }
                ],
                "content_quality": "sufficient",
            }
        if purpose == "importance":
            return {"scope": 2, "durability": 2, "novelty": 2}
        parsed = json.loads(user)
        if purpose == "grounding" and "facts" in parsed:
            return {"supported_fact_indexes": list(range(len(parsed["facts"])))}
        if purpose == "grounding":
            return self.last_viewpoint
        self.last_viewpoint = {
            "claims": [
                {
                    "article_id": a["article_id"],
                    "claim": "Bridge reopened",
                    "evidence_quote": "The bridge reopened at 11:00.",
                }
                for a in parsed["articles"]
            ],
            "disagreements": [],
        }
        return self.last_viewpoint

    def embed(self, session: Session, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        session.add(LlmUsage(purpose="embedding", model="fake", cost_usd=0.001))
        if self.fail_embedding:
            raise RuntimeError("embedding failed after billing")
        return [[1.0] + [0.0] * (EMBEDDING_DIM - 1) for _ in texts]


def seed(session: Session) -> Event:
    now = datetime(2026, 10, 1, tzinfo=UTC)
    event = Event(title="Old title", summary_zh="Unsupported old summary", changed_at=now)
    session.add(event)
    for i, source in enumerate(["bbc-world", "caixin", "nyt-world"]):
        session.add(
            Article(
                source_id=source,
                title="Bridge reopened",
                title_zh="Old title",
                content="The bridge reopened at 11:00.",
                summary_zh="Old summary",
                event=event,
                url=f"https://example.com/repair/{i}",
                published_at=now,
            )
        )
    session.flush()
    return event


def test_dry_run_lists_affected_articles_without_calls_or_mutation(db_session: Session) -> None:
    event = seed(db_session)
    client = RepairLlm()
    result = repair_event(db_session, client, event.id)
    assert result["applied"] is False
    assert set(result["article_ids"]) == {a.id for a in event.articles}
    assert client.calls == 0
    assert event.summary_zh == "Unsupported old summary"


def test_repair_updates_dependencies_but_preserves_history_and_event_time(
    db_session: Session,
) -> None:
    event = seed(db_session)
    old_time = event.changed_at
    from datetime import date

    snapshot = Digest(
        report_date=date(2099, 1, 1), payload={"intro": "immutable old digest", "events": []}
    )
    db_session.add(snapshot)
    db_session.flush()
    result = repair_event(db_session, RepairLlm(), event.id, apply=True)
    assert result["applied"] is True
    assert all(a.summary_grounding is not None and a.embedding is not None for a in event.articles)
    assert event.summary_zh == "\u6865\u6881\u4e8e11:00\u6062\u590d\u5f00\u653e\u3002"
    assert event.score_final is not None
    assert event.centroid is not None
    assert event.viewpoint is not None
    assert event.changed_at == old_time
    assert snapshot.payload["intro"] == "immutable old digest"
    assert (db_session.scalar(select(func.count(LlmUsage.id))) or 0) > 0


def test_failed_generation_preserves_usage_and_original_business_data(db_session: Session) -> None:
    event = seed(db_session)
    ids = [a.id for a in event.articles]
    before = db_session.scalar(select(func.count(LlmUsage.id))) or 0
    with pytest.raises(RuntimeError, match="embedding failed"):
        repair_event(db_session, RepairLlm(fail_embedding=True), event.id, apply=True)
    db_session.expire_all()
    assert event.summary_zh == "Unsupported old summary"
    for id_ in ids:
        article = db_session.get(Article, id_)
        assert article is not None
        assert article.summary_zh == "Old summary"
    assert (db_session.scalar(select(func.count(LlmUsage.id))) or 0) > before


def test_missing_event_and_article_cap_fail_before_any_paid_call(db_session: Session) -> None:
    client = RepairLlm()
    with pytest.raises(ValueError, match="not found"):
        repair_event(db_session, client, 99999999, apply=True)
    event = seed(db_session)
    with pytest.raises(ValueError, match="article cap"):
        repair_event(db_session, client, event.id, apply=True, max_articles=1)
    assert client.calls == 0


def test_call_cap_preserves_original_rows_and_billed_usage(db_session: Session) -> None:
    event = seed(db_session)
    before = db_session.scalar(select(func.count(LlmUsage.id))) or 0
    from unspun.core.llm import LlmError

    with pytest.raises(LlmError, match="call cap"):
        repair_event(db_session, RepairLlm(), event.id, apply=True, max_calls=1)
    db_session.expire_all()
    assert event.title == "Old title"
    assert event.summary_zh == "Unsupported old summary"
    assert all(a.summary_zh == "Old summary" for a in event.articles)
    assert (db_session.scalar(select(func.count(LlmUsage.id))) or 0) == before + 1


def test_budget_limited_repair_does_not_overwrite_existing_good_data(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unspun.core.config import get_settings
    from unspun.core.llm import LlmError

    event = seed(db_session)
    monkeypatch.setattr(get_settings(), "grounding_budget_24h_usd", 0.0)
    with pytest.raises(LlmError, match="budget"):
        repair_event(db_session, RepairLlm(), event.id, apply=True)
    db_session.expire_all()
    assert event.summary_zh == "Unsupported old summary"
    assert all(a.summary_zh == "Old summary" for a in event.articles)
