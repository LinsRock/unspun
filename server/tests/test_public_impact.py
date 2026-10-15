from datetime import UTC, datetime
from typing import Any

import pytest

NOW = datetime(2026, 10, 14, 5, 53, tzinfo=UTC)


def article(
    article_id: int = 1,
    body: str = "Five people were killed and thirty injured in a train derailment on Tuesday.",
) -> dict[str, Any]:
    return {
        "id": article_id,
        "title": "Train incident",
        "text": body,
        "reported_at": NOW.isoformat(),
    }


def parse(payload: dict[str, Any], articles: list[dict[str, Any]] | None = None):
    from unspun.core.public_impact import ImpactArticle, parse_impact

    return parse_impact(payload, [ImpactArticle.model_validate(a) for a in articles or [article()]])


def test_supported_urgency_requires_member_original_evidence() -> None:
    result = parse(
        {
            "is_urgent": True,
            "reason": "Recent loss of life",
            "evidence": [{"article_id": 1, "quote": "Five people were killed and thirty injured"}],
        }
    )
    assert result.status == "supported"
    assert result.is_urgent is True
    assert result.evidence[0].article_id == 1


@pytest.mark.parametrize(
    "evidence",
    [
        [],
        [{"article_id": 999, "quote": "Five people were killed"}],
        [{"article_id": 1, "quote": "A million people died"}],
        [{"article_id": True, "quote": "Five people were killed"}],
    ],
)
def test_unsupported_or_foreign_evidence_cannot_promote_urgency(evidence: Any) -> None:
    result = parse({"is_urgent": True, "reason": "Urgent", "evidence": evidence})
    assert result.is_urgent is False
    assert result.status == "unknown"


def test_routine_product_update_does_not_need_a_fabricated_harm_quote() -> None:
    result = parse({"is_urgent": False, "reason": "Routine product release", "evidence": []})
    assert result.is_urgent is False
    assert result.status == "routine"


def test_string_true_and_empty_reason_are_not_accepted() -> None:
    assert parse({"is_urgent": "true", "reason": "Urgent", "evidence": []}).status == "unknown"
    assert parse({"is_urgent": True, "reason": "", "evidence": []}).status == "unknown"


def test_generated_titles_are_not_original_body_evidence() -> None:
    sample = article(body="The article has no casualty report.")
    sample["title"] = "Five people were killed"
    result = parse(
        {
            "is_urgent": True,
            "reason": "Casualties",
            "evidence": [{"article_id": 1, "quote": "Five people were killed"}],
        },
        [sample],
    )
    assert result.status == "unknown"


def test_input_fingerprint_changes_with_membership_body_model_and_time() -> None:
    from unspun.core.public_impact import ImpactArticle, impact_fingerprint

    a = ImpactArticle.model_validate(article())
    b = ImpactArticle.model_validate(article(2))
    initial = impact_fingerprint([a], "model-a")
    assert initial != impact_fingerprint([a, b], "model-a")
    assert initial != impact_fingerprint([a], "model-b")
    assert initial == impact_fingerprint([a], "model-a")
    assert impact_fingerprint([a, b], "model-a") == impact_fingerprint([b, a], "model-a")
    revised = a.model_copy(update={"text": "Revised content"})
    assert initial != impact_fingerprint([revised], "model-a")


def test_prompt_separates_public_impact_from_volume_and_historical_references() -> None:
    from unspun.core.public_impact import IMPACT_SYSTEM, ImpactArticle, impact_prompt

    assert "historical" in IMPACT_SYSTEM.lower()
    assert "protective" in IMPACT_SYSTEM.lower()
    assert "coverage" in IMPACT_SYSTEM.lower()
    assert "instructions" in IMPACT_SYSTEM.lower()
    prompt = impact_prompt([ImpactArticle.model_validate(article())], NOW)
    assert "2026-10-14" in prompt
    assert "Five people" in prompt


def test_assessment_budget_failure_does_not_call_model(db_session: Any, monkeypatch: Any) -> None:
    from unspun.core.public_impact import ImpactArticle, assess_impact
    from unspun.core.review_budget import GroundingBudgetExceeded

    def reject(*args: Any) -> None:
        raise GroundingBudgetExceeded("limit")

    monkeypatch.setattr("unspun.core.public_impact.require_grounding_budget", reject)

    class NoCall:
        def chat_json(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            pytest.fail("budget-limited assessment must not call model")

        def embed(self, *args: Any, **kwargs: Any) -> list[list[float]]:
            pytest.fail("assessment must not embed")

    result = assess_impact(
        db_session, NoCall(), [ImpactArticle.model_validate(article())], NOW, "model"
    )
    assert result.status == "unknown"
    assert result.failure_kind == "budget"
    assert result.is_urgent is False


def test_model_cannot_quote_unseen_members_or_truncated_body(db_session: Any) -> None:
    from unspun.core.public_impact import ImpactArticle, assess_impact

    class FakeClient:
        def chat_json(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {
                "is_urgent": True,
                "reason": "Urgent",
                "evidence": [{"article_id": 1, "quote": "Hidden casualties"}],
            }

        def embed(self, *args: Any, **kwargs: Any) -> list[list[float]]:
            return []

    result = assess_impact(
        db_session,
        FakeClient(),
        [ImpactArticle.model_validate(article(body="x" * 2500 + "Hidden casualties"))],
        NOW,
        "model",
    )
    assert result.status == "unknown"


def test_assessment_rejects_naive_snapshot_even_without_material(db_session: Any) -> None:
    from unspun.core.public_impact import assess_impact

    class NoCall:
        def chat_json(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            pytest.fail("naive snapshot must fail before model call")

        def embed(self, *args: Any, **kwargs: Any) -> list[list[float]]:
            return []

    with pytest.raises(ValueError, match="timezone"):
        assess_impact(db_session, NoCall(), [], NOW.replace(tzinfo=None), "model")


def test_empty_legacy_members_do_not_hide_available_original_body(db_session: Any) -> None:
    from unspun.core.public_impact import ImpactArticle, assess_impact

    class Client:
        def chat_json(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            import json

            prompt = json.loads(kwargs["user"])
            assert prompt["members_total"] == 9
            assert [a["id"] for a in prompt["articles"]] == [9]
            return {
                "is_urgent": True,
                "reason": "Recent serious harm",
                "evidence": [{"article_id": 9, "quote": "Five people were killed"}],
            }

        def embed(self, *args: Any, **kwargs: Any) -> list[list[float]]:
            return []

    members = [ImpactArticle.model_validate(article(i, "")) for i in range(1, 9)]
    members.append(ImpactArticle.model_validate(article(9)))
    result = assess_impact(db_session, Client(), members, NOW, "model")
    assert result.status == "supported"
