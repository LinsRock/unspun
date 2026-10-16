import json
import math
from collections.abc import Callable, Generator
from contextlib import nullcontext
from typing import Any, cast

import httpx
import pytest
from sqlalchemy.orm import Session

from tests.billing_fakes import RecordingJournal
from unspun.core.config import get_settings
from unspun.core.llm import LlmClient, LlmError, parse_json_content, truncate_embedding
from unspun.core.models import EMBEDDING_DIM


def chat_response(content: str, finish_reason: str) -> dict[str, Any]:
    return {
        "choices": [{"finish_reason": finish_reason, "message": {"content": content}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.001},
    }


Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture
def llm_client_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[Callable[[Handler], LlmClient]]:
    monkeypatch.setenv("UNSPUN_OPENROUTER_API_KEY", "test-key")
    get_settings.cache_clear()

    def factory(handler: Handler) -> LlmClient:
        return LlmClient(transport=httpx.MockTransport(handler), journal_factory=RecordingJournal)

    yield factory
    get_settings.cache_clear()


class RecordingSession:
    """Stands in for a DB session; chat_json only calls session.add()."""

    def __init__(self) -> None:
        self.added: list[Any] = []

    @property
    def new(self) -> list[Any]:
        return self.added

    no_autoflush = nullcontext()

    def scalar(self, statement: Any) -> float:
        return 0.0

    def add(self, obj: Any) -> None:
        self.added.append(obj)


def test_chat_json_retries_truncated_completion(
    llm_client_factory: Callable[[Handler], LlmClient],
) -> None:
    requested_max_tokens: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requested_max_tokens.append(payload["max_tokens"])
        if len(requested_max_tokens) == 1:
            return httpx.Response(200, json=chat_response('{"summary_zh": "cut of', "length"))
        return httpx.Response(200, json=chat_response('{"summary_zh": "ok"}', "stop"))

    session = RecordingSession()
    with llm_client_factory(handler) as client:
        out = client.chat_json(
            cast(Session, session),
            model="google/gemini-2.5-flash-lite",
            system="s",
            user="u",
            purpose="summary",
        )
    assert out == {"summary_zh": "ok"}
    assert requested_max_tokens == [1024, 2048]
    # Both attempts cost money, so both must be recorded.
    assert len(session.added) == 2


def test_chat_json_keeps_parseable_completion_despite_length(
    llm_client_factory: Callable[[Handler], LlmClient],
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=chat_response('{"summary_zh": "ok"}', "length"))

    session = RecordingSession()
    with llm_client_factory(handler) as client:
        out = client.chat_json(
            cast(Session, session),
            model="google/gemini-2.5-flash-lite",
            system="s",
            user="u",
            purpose="summary",
        )
    assert out == {"summary_zh": "ok"}
    assert calls == 1


def test_chat_json_raises_after_second_truncation(
    llm_client_factory: Callable[[Handler], LlmClient],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=chat_response('{"summary_zh": "cut', "length"))

    session = RecordingSession()
    with llm_client_factory(handler) as client, pytest.raises(LlmError, match="truncated"):
        client.chat_json(
            cast(Session, session),
            model="google/gemini-2.5-flash-lite",
            system="s",
            user="u",
            purpose="summary",
        )
    assert len(session.added) == 2


def test_truncate_embedding_truncates_and_normalizes() -> None:
    vector = [2.0] * (EMBEDDING_DIM * 2)
    out = truncate_embedding(vector)
    assert len(out) == EMBEDDING_DIM
    assert math.isclose(math.sqrt(sum(x * x for x in out)), 1.0, rel_tol=1e-9)


def test_truncate_embedding_rejects_short_vectors() -> None:
    with pytest.raises(LlmError):
        truncate_embedding([1.0] * (EMBEDDING_DIM - 1))


def test_truncate_embedding_rejects_zero_norm() -> None:
    with pytest.raises(LlmError):
        truncate_embedding([0.0] * EMBEDDING_DIM)


def test_parse_json_content_plain_and_fenced() -> None:
    assert parse_json_content('{"a": 1}') == {"a": 1}
    assert parse_json_content('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_json_content_rejects_non_object() -> None:
    with pytest.raises(LlmError):
        parse_json_content("[1, 2]")


@pytest.mark.parametrize("purpose", ["summary", "viewpoint", "grounding"])
def test_evidence_generation_uses_deterministic_sampling(
    llm_client_factory: Callable[[Handler], LlmClient],
    purpose: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["temperature"] == 0
        return httpx.Response(200, json=chat_response("{}", "stop"))

    with llm_client_factory(handler) as client:
        client.chat_json(
            cast(Session, RecordingSession()),
            model="google/gemini-2.5-flash-lite",
            system="s",
            user="u",
            purpose=purpose,
        )


def test_grounding_cap_prevents_another_billed_truncation_retry(
    llm_client_factory: Callable[[Handler], LlmClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unspun.core.review_budget import GroundingBudgetExceeded

    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=chat_response('{"cut', "length"))

    session = RecordingSession()
    with llm_client_factory(handler) as client:
        monkeypatch.setattr(get_settings(), "grounding_budget_24h_usd", 0.0005)
        with pytest.raises(GroundingBudgetExceeded):
            client.chat_json(
                cast(Session, session),
                model="google/gemini-2.5-flash-lite",
                system="s",
                user="u",
                purpose="grounding",
            )
    assert calls == 1
    assert len(session.added) == 1
