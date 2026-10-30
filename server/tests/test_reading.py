from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.reading_fixtures import approve
from tests.test_summary_grounding import ResponseLlm
from unspun.api.events import event_out
from unspun.core.feed_query import feed_page
from unspun.core.models import Article, Event
from unspun.core.reading import (
    attach_reading,
    chinese_text,
    current_reading,
    event_reading,
    ready_condition,
)
from unspun.core.review_budget import GroundingBudgetExceeded
from unspun.evaluation.legacy.summarize import pending_summary_ids, summarize_article


def material(number: int = 1) -> Article:
    a = Article(id=number, title="A launch", source_id="test", url=f"https://test/{number}")
    approve(a)
    return a


def test_language_allows_names_but_rejects_english_paragraphs() -> None:
    assert chinese_text("OpenAI \u53d1\u5e03 GPT \u6a21\u578b\u3002")
    assert not chinese_text("English title without translation")
    assert not chinese_text(
        "\u4e2d\u6587\u3002This entire body is still in English and has not been translated."
    )


def test_title_only_and_unverified_material_are_not_published() -> None:
    a = material()
    a.summary_grounding = {"status": "review_limited"}
    attach_reading(a)
    assert current_reading(a)["reason"] == "review_budget"
    approve(a)
    assert a.summary_grounding is not None
    a.summary_grounding = {
        **(a.summary_grounding or {}),
        "facts": [{"text": a.title_zh, "quote": a.title}],
    }
    attach_reading(a)
    assert current_reading(a)["reason"] == "no_added_facts"
    approve(a)
    assert a.summary_grounding is not None
    a.summary_grounding = {**(a.summary_grounding or {}), "title_verified": False}
    attach_reading(a)
    assert current_reading(a)["reason"] == "title_unverified"


def test_mixed_language_is_withheld_and_quotes_must_exist() -> None:
    a = material()
    assert a.summary_grounding is not None
    a.summary_grounding["facts"].append({"text": "Untranslated body", "quote": a.content})
    attach_reading(a)
    assert current_reading(a)["reason"] == "language_invalid"
    approve(a)
    assert a.summary_grounding is not None
    a.summary_grounding["facts"][0]["quote"] = "Invented quote"
    attach_reading(a)
    assert current_reading(a)["status"] == "withheld"


def test_duplicate_sources_do_not_create_aggregation_or_repeat_facts() -> None:
    a, b = material(1), material(2)
    result = event_reading([a, b])
    assert result["kind"] == "brief"
    assert len(result["facts"]) == 1
    assert b.summary_grounding is not None
    assert b.content is not None
    b.content += " Scientists released measurements."
    b.summary_grounding["facts"].append(
        {
            "text": "\u56e2\u961f\u516c\u5e03\u6d4b\u91cf\u6570\u636e\u3002",
            "quote": "Scientists released measurements.",
        }
    )
    attach_reading(b)
    result = event_reading([a, b])
    # The richer representative already contains all distinct facts.
    assert len(result["facts"]) == 2
    assert result["title"] == b.title_zh


def test_source_edits_invalidate_python_and_sql_projection(db_session: Session) -> None:
    a = material()
    db_session.add(a)
    db_session.flush()
    assert db_session.scalar(select(Article.id).where(ready_condition())) == a.id
    a.content = "Changed source"
    db_session.flush()
    assert current_reading(a)["status"] == "withheld"
    assert db_session.scalar(select(Article.id).where(ready_condition())) is None


def test_publication_filter_runs_before_pagination_and_review_invalidates_cursor(
    db_session: Session,
) -> None:
    now = datetime.now(UTC)
    events: list[Event] = []
    for number in range(1, 7):
        event = Event(
            title="bad legacy title",
            summary_zh="bad legacy title",
            first_seen_at=now - timedelta(hours=number),
            changed_at=now,
        )
        a = material(number)
        a.event = event
        a.fetched_at = now - timedelta(hours=number)
        if number % 2:
            a.summary_grounding = {"status": "review_limited"}
        db_session.add(event)
        events.append(event)
    db_session.flush()
    first = feed_page(db_session, "newest", "all", 2, now, None, publishable_only=True)
    assert [r["id"] for r in first.rows] == [events[1].id, events[3].id]
    second = feed_page(
        db_session, "newest", "all", 2, now, first.next_cursor, publishable_only=True
    )
    assert [r["id"] for r in second.rows] == [events[5].id]
    dto = event_out(events[1], None, {}, published=True)
    assert dto.title == events[1].articles[0].title_zh
    assert dto.facts[0].article_id == events[1].articles[0].id
    approve(events[0].articles[0])
    db_session.flush()
    with pytest.raises(HTTPException) as error:
        feed_page(db_session, "newest", "all", 2, now, first.next_cursor, publishable_only=True)
    assert error.value.status_code == 409


def test_legacy_budget_fallback_is_pending_again(db_session: Session) -> None:
    a = material()
    a.summary_zh = a.title
    a.summary_grounding = {"status": "review_limited"}
    db_session.add(a)
    db_session.flush()
    assert a.id in pending_summary_ids(db_session, 100)
    assert current_reading(a)["reason"] == "review_budget"


def test_deferred_backlog_does_not_starve_new_reports(db_session: Session) -> None:
    now = datetime.now(UTC)
    older, newer = material(1), material(2)
    older.published_at = now - timedelta(days=2)
    older.summary_grounding = {"status": "review_limited"}
    newer.published_at = now
    newer.summary_grounding = None
    newer.summary_zh = None
    db_session.add_all([older, newer])
    db_session.flush()
    assert pending_summary_ids(db_session, 2) == [newer.id, older.id]


def test_budget_resume_reuses_draft_without_second_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unspun.evaluation.legacy import summarize as module

    a = material()
    response = {
        "title_zh": a.title_zh,
        "facts": (a.summary_grounding or {})["facts"],
        "content_quality": "sufficient",
    }
    client = ResponseLlm(response)
    verify = module.verify_facts

    def exhausted(*args: object, **kwargs: object) -> list[dict[str, str]]:
        raise GroundingBudgetExceeded("budget")

    monkeypatch.setattr(module, "verify_facts", exhausted)
    with Session() as session:
        summarize_article(session, client, a)
        assert a.title_zh is None and a.summary_zh is None
        assert current_reading(a)["reason"] == "review_budget"
        monkeypatch.setattr(module, "verify_facts", verify)
        summarize_article(session, client, a)
    assert client.purposes == ["summary", "grounding"]
    assert current_reading(a)["status"] == "ready"


def test_fact_identity_preserves_numeric_meaning() -> None:
    from unspun.core.reading import fact_key

    assert fact_key("1.2 percent") != fact_key("12 percent")
    assert fact_key("-1 degrees") != fact_key("1 degrees")


def test_unrelated_cluster_member_cannot_supply_event_facts() -> None:
    a, b = material(1), material(2)
    a.title_zh = "\u536b\u661f\u53d1\u5c04\u5b8c\u6210\u9996\u6b21\u7ed5\u8f68"
    attach_reading(a)
    b.title = "A completely unrelated exhibition"
    b.title_zh = "\u7f8e\u672f\u9986\u5c55\u89c8\u63a5\u53d7\u516c\u4f17\u9884\u7ea6"
    b.content = "Exhibition booking opens on Monday."
    b.summary_grounding = {
        "status": "grounded",
        "title_verified": True,
        "facts": [
            {
                "text": "\u5c55\u89c8\u9884\u7ea6\u5c06\u5728\u5468\u4e00\u5f00\u653e\u3002",
                "quote": b.content,
            }
        ],
        "verification": {"method": "source_entailment_review"},
    }
    attach_reading(b)
    projection = event_reading([a, b])
    assert projection["article_ids"] == [a.id]
    assert {fact["article_id"] for fact in projection["facts"]} == {a.id}


@pytest.mark.legacy_batch
def test_batch_budget_preflight_keeps_retryable_state_without_generation(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from collections.abc import Generator
    from contextlib import contextmanager

    from unspun.core.config import get_settings
    from unspun.evaluation.legacy import summarize as module

    a = Article(source_id="test", title="Original English", url="https://test/budget")
    db_session.add(a)
    db_session.flush()

    @contextmanager
    def scoped() -> Generator[Session]:
        yield db_session
        db_session.flush()

    monkeypatch.setattr(module, "session_scope", scoped)
    monkeypatch.setattr(get_settings(), "grounding_budget_24h_usd", 0)
    client = ResponseLlm({})
    assert module.summarize_pending(client) == 0
    assert client.calls == 0
    assert current_reading(a)["reason"] == "review_budget"
    assert a.summary_failures == 0
    assert a.id in pending_summary_ids(db_session, 10)


@pytest.mark.legacy_batch
def test_exact_duplicate_reuses_review_without_budget_or_provider_call(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from collections.abc import Generator
    from contextlib import contextmanager

    from unspun.core.config import get_settings
    from unspun.evaluation.legacy import summarize as module

    a = material()
    b = Article(id=2, source_id="other", title=a.title, content=a.content, url="https://test/copy")
    db_session.add_all([a, b])
    db_session.flush()

    @contextmanager
    def scoped() -> Generator[Session]:
        yield db_session
        db_session.flush()

    monkeypatch.setattr(module, "session_scope", scoped)
    monkeypatch.setattr(get_settings(), "grounding_budget_24h_usd", 0)
    client = ResponseLlm({})
    assert module.summarize_pending(client) == 1
    assert client.calls == 0
    assert current_reading(b)["status"] == "ready"
    assert (b.summary_grounding or {})["duplicate_of"] == a.id
    assert b.url != a.url and b.source_id != a.source_id


def test_source_edit_is_pending_again(db_session: Session) -> None:
    a = material()
    db_session.add(a)
    db_session.flush()
    assert a.id not in pending_summary_ids(db_session, 10)
    a.content = "Changed source material"
    db_session.flush()
    assert a.id in pending_summary_ids(db_session, 10)


def test_legacy_hydration_uses_only_provable_v5_title_verdict() -> None:
    from unspun.core.reading import hydrate_legacy_reading

    a = material()
    grounding = dict(a.summary_grounding or {})
    grounding.pop("reading")
    grounding.pop("title_verified")
    grounding["version"] = "summary-grounded-v5"
    a.summary_grounding = grounding
    assert hydrate_legacy_reading(a)
    assert current_reading(a)["status"] == "ready"
    assert (a.summary_grounding or {})[
        "title_verification_basis"
    ] == "v5_supported_translation_branch"
    a.summary_grounding = grounding
    a.title_zh = a.title
    assert not hydrate_legacy_reading(a)
    a = material()
    a.summary_grounding = {**grounding, "status": "review_limited"}
    assert not hydrate_legacy_reading(a)
    a.summary_grounding = {**grounding, "version": "unknown"}
    assert not hydrate_legacy_reading(a)
