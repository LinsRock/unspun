"""Grounding remains current when a card reuses its claim as the reading reason."""

import pytest

from tests.test_content_processing import TEXT, draft, input_content
from unspun.core import content_reading
from unspun.core.content import Paragraph
from unspun.core.content_reading import CardDraft, EvidenceClaim


def test_equal_reading_reason_reuses_only_current_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    card = CardDraft.model_validate(draft())
    assert card.reading_reason == card.claims[0]
    assert card.reading_reason is not card.claims[0]
    validate = content_reading.claim_valid
    calls = 0

    def observed(claim: EvidenceClaim, source: str, scope: content_reading.MaterialScope) -> bool:
        nonlocal calls
        calls += 1
        return validate(claim, source, scope)

    monkeypatch.setattr(content_reading, "claim_valid", observed)
    content = input_content()
    assert content_reading.card_valid(card, content)
    assert calls == 1
    # A second invocation must revalidate the same IDs against their current material.
    changed = content.model_copy(update={"paragraphs": (Paragraph(text=TEXT[:8]),)})
    assert not content_reading.card_valid(card, changed)
    assert calls == 2
    assert content_reading.card_valid(card, content)
    assert calls == 3


@pytest.mark.parametrize("include", [True, False])
@pytest.mark.parametrize("reason", ["equal", "distinct_supported", "unsupported", "absent"])
def test_reading_reason_keeps_grounding_and_membership_rules(include: bool, reason: str) -> None:
    card = CardDraft.model_validate(draft(include=include))
    value = card.reading_reason
    assert value is not None
    if reason == "distinct_supported":
        value = value.model_copy(update={"text": TEXT + " "})
    elif reason == "unsupported":
        value = value.model_copy(update={"quote": TEXT[::-1]})
    elif reason == "absent":
        value = None
    card = card.model_copy(update={"reading_reason": value})
    expected = reason == "equal" or (not include and reason in {"distinct_supported", "absent"})
    assert content_reading.card_valid(card, input_content()) is expected
