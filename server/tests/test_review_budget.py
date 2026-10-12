from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from unspun.core.config import get_settings
from unspun.core.models import LlmUsage
from unspun.core.review_budget import GroundingBudgetExceeded, require_grounding_budget


def test_review_budget_counts_only_recent_grounding_and_pending_usage(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "grounding_budget_24h_usd", 0.4)
    now = datetime.now(UTC)
    db_session.add_all(
        [
            LlmUsage(
                purpose="grounding", model="m", cost_usd=0.9, created_at=now - timedelta(hours=25)
            ),
            LlmUsage(purpose="summary", model="m", cost_usd=1.0, created_at=now),
            LlmUsage(purpose="grounding", model="m", cost_usd=0.3, created_at=now),
        ]
    )
    db_session.flush()
    require_grounding_budget(db_session)
    db_session.add(LlmUsage(purpose="grounding", model="m", cost_usd=0.1))
    with pytest.raises(GroundingBudgetExceeded):
        require_grounding_budget(db_session)


def test_zero_budget_disables_review_without_provider_calls(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "grounding_budget_24h_usd", 0.0)
    with pytest.raises(GroundingBudgetExceeded):
        require_grounding_budget(db_session)
