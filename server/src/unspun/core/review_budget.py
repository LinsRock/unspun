"""Bound added semantic-review spend using recorded rolling 24-hour usage.

This stops subsequent requests, not a provider request already in flight.
Concurrent callers and a single request's actual cost can slightly exceed the
limit. Failed and truncated billed responses count toward the same allowance.
"""

from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from unspun.core.config import get_settings
from unspun.core.llm import LlmError
from unspun.core.models import LlmUsage


class GroundingBudgetExceeded(LlmError):
    pass


def _recent_or_pending(item: LlmUsage, since: datetime) -> bool:
    # Server defaults are absent until an ORM object is flushed.
    created = cast(datetime | None, item.created_at)
    return created is None or created >= since


def require_grounding_budget(session: Session) -> None:
    limit = get_settings().grounding_budget_24h_usd
    since = datetime.now(UTC) - timedelta(hours=24)
    with session.no_autoflush:
        recorded = float(
            session.scalar(
                select(func.coalesce(func.sum(LlmUsage.cost_usd), 0)).where(
                    LlmUsage.purpose == "grounding",
                    LlmUsage.created_at >= since,
                )
            )
            or 0
        )
    pending = sum(
        float(item.cost_usd or 0)
        for item in session.new
        if isinstance(item, LlmUsage)
        and item.purpose == "grounding"
        and _recent_or_pending(item, since)
    )
    if recorded + pending >= limit:
        raise GroundingBudgetExceeded("rolling grounding review budget exhausted")
