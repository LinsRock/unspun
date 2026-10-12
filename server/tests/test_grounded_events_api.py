from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from unspun.api.events import EventOut, event_out, viewpoint_out
from unspun.core.models import Article, Event, EventViewpoint


def test_api_preserves_evidence_and_kind_when_remapping_claims() -> None:
    row = EventViewpoint(
        event_id=1,
        input_fingerprint="f",
        model="m",
        generated_at=datetime.now(UTC),
        payload={
            "claims": [
                {"article_id": 1, "claim": "a", "evidence_quote": "Original evidence one"},
                {"article_id": 999, "claim": "foreign", "evidence_quote": "Other event evidence"},
                {"article_id": 2, "claim": "b", "evidence_quote": "Original evidence two"},
            ],
            "disagreements": [
                {"point": "A later update", "claim_indexes": [0, 2], "kind": "temporal_update"}
            ],
        },
    )
    out = viewpoint_out(row, {1, 2})
    assert out is not None
    payload = out.model_dump()
    assert payload["claims"][0]["evidence_quote"] == "Original evidence one"
    assert payload["disagreements"][0]["kind"] == "temporal_update"
    assert payload["disagreements"][0]["claim_indexes"] == [0, 1]


@pytest.mark.parametrize("quality", ["limited", "review_limited"])
def test_event_api_exposes_limited_content_without_mutating_article(
    db_session: Session, quality: str
) -> None:
    event = Event(title="sparse source")
    article = Article(
        source_id="sample",
        title="Only a title",
        url="https://example.com/limited",
        event=event,
        summary_grounding={"version": "summary-grounded-v1", "status": quality, "facts": []},
    )
    db_session.add_all([event, article])
    db_session.flush()
    out = event_out(event, None, {})
    assert out.model_dump()["articles"][0]["content_quality"] == quality


def test_old_snapshot_defaults_optional_grounding_fields() -> None:
    event = EventOut.model_validate(
        {
            "id": 1,
            "title": "old snapshot",
            "summary_zh": "old summary",
            "score_final": 1,
            "score_decayed": 1,
            "score_breakdown": None,
            "first_seen_at": "2026-10-10T00:00:00Z",
            "changed_at": "2026-10-10T00:00:00Z",
            "articles": [
                {
                    "id": 1,
                    "title": "old source",
                    "title_zh": None,
                    "url": "https://example.com/old",
                    "source_id": "s",
                    "source_name": "s",
                    "published_at": None,
                }
            ],
            "viewpoint": {
                "claims": [{"article_id": 1, "claim": "old claim"}],
                "disagreements": [{"point": "old point", "claim_indexes": [0, 1]}],
                "model": "m",
                "generated_at": "2026-10-10T00:00:00Z",
            },
        }
    )
    payload = event.model_dump()
    assert payload["articles"][0]["content_quality"] is None
    assert payload["viewpoint"]["claims"][0]["evidence_quote"] is None
    assert payload["viewpoint"]["disagreements"][0]["kind"] is None


def test_api_exposes_review_pause_even_when_no_claims_are_available() -> None:
    row = EventViewpoint(
        event_id=1,
        input_fingerprint="f",
        model="m",
        generated_at=datetime.now(UTC),
        payload={"claims": [], "disagreements": [], "status": "review_limited"},
    )
    out = viewpoint_out(row, set())
    assert out is not None
    assert out.model_dump()["status"] == "review_limited"
