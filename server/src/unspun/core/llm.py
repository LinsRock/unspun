"""Thin OpenRouter client; every call records tokens and cost in llm_usage."""

from __future__ import annotations

import copy
import json
import math
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol, cast

import httpx
from sqlalchemy.orm import Session

from unspun.core.config import get_settings
from unspun.core.models import EMBEDDING_DIM

if TYPE_CHECKING:
    from unspun.core.billing import CallContext, CallJournal

CHAT_TIMEOUT_SECONDS = 120


class LlmError(RuntimeError):
    pass


class SupportsLlm(Protocol):
    """Structural interface so pipeline stages can be tested with fakes."""

    def chat_json(
        self,
        session: Session,
        *,
        model: str,
        system: str,
        user: str,
        purpose: str,
        max_tokens: int = 1024,
    ) -> dict[str, Any]: ...

    def embed(self, session: Session, texts: list[str]) -> list[list[float]]: ...


def truncate_embedding(vector: list[float], dim: int = EMBEDDING_DIM) -> list[float]:
    """MRL-truncate to the schema dimension and L2-normalize.

    Defensive: if the provider ignores the `dimensions` request parameter the
    raw vector comes back wider than our pgvector columns.
    """
    head = vector[:dim]
    if len(head) < dim:
        raise LlmError(f"embedding has {len(vector)} dims, schema needs {dim}")
    norm = math.sqrt(sum(x * x for x in head))
    if norm == 0:
        raise LlmError("zero-norm embedding")
    return [x / norm for x in head]


def parse_json_content(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.removeprefix("json").strip()
    parsed: Any = json.loads(text)
    if not isinstance(parsed, dict):
        raise LlmError(f"expected a JSON object, got {type(parsed).__name__}")
    return parsed  # pyright: ignore[reportUnknownVariableType]


class LlmClient:
    def __init__(
        self,
        transport: httpx.BaseTransport | None = None,
        *,
        context: CallContext | None = None,
        journal_factory: Callable[[Session], CallJournal] | None = None,
    ) -> None:
        from unspun.core.billing import CallContext, DatabaseJournal

        self._context = context or CallContext()
        self._journal_factory: Callable[[Session], CallJournal] = journal_factory or (
            lambda session: DatabaseJournal(session.get_bind().engine)
        )
        self.call_ids: list[str] = []
        settings = get_settings()
        if not settings.openrouter_api_key:
            raise LlmError("UNSPUN_OPENROUTER_API_KEY is not set")
        self._client = httpx.Client(
            base_url=settings.openrouter_base_url,
            headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
            timeout=CHAT_TIMEOUT_SECONDS,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> LlmClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _post(
        self, session: Session, endpoint: str, purpose: str, model: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        from unspun.core.billing import UsageUnknown, provider_cap

        payload = {**payload, "provider": provider_cap(model)}
        journal = self._journal_factory(session)
        reservation = journal.reserve(
            purpose=purpose, model=model, request=payload, context=self._context
        )
        self.call_ids.append(reservation.id)
        if reservation.response is not None:
            return copy.deepcopy(reservation.response)
        try:
            response = self._client.post(endpoint, json=payload)
        except BaseException as error:
            journal.unknown(reservation.id, type(error).__name__)
            raise
        try:
            data: Any = response.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            journal.unknown(reservation.id, "response JSON unavailable", response.status_code)
            response.raise_for_status()
            raise LlmError("provider response is not JSON") from None
        if not isinstance(data, dict):
            journal.unknown(reservation.id, "response object unavailable", response.status_code)
            raise LlmError("provider response is not an object")
        parsed = cast(dict[str, Any], data)
        known = journal.finish(reservation.id, parsed, response.status_code)
        response.raise_for_status()
        if not known:
            raise UsageUnknown("provider cost missing; reservation retained")
        return parsed

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
        # Models that spend reasoning tokens can exhaust the completion budget
        # and return JSON cut off mid-string; one retry with a doubled budget
        # recovers those instead of failing the article every cycle.
        for attempt_max_tokens in (max_tokens, max_tokens * 2):
            if purpose == "grounding" and self._context.stage == "legacy":
                from unspun.core.review_budget import require_grounding_budget

                require_grounding_budget(session)
            # R1 uses DatabaseJournal's same rolling cap plus reservations. It
            # closes that independent transaction before HTTP; opening the old
            # caller-session guard here would hold a task DB transaction open.
            data = self._post(
                session,
                "/chat/completions",
                purpose,
                model,
                {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "response_format": {"type": "json_object"},
                    "usage": {"include": True},
                    "max_tokens": attempt_max_tokens,
                    **(
                        {"temperature": 0}
                        if purpose in {"summary", "viewpoint", "grounding"}
                        else {}
                    ),
                },
            )
            choice: dict[str, Any] = data["choices"][0]
            content = str(choice["message"]["content"])
            if choice.get("finish_reason") == "length":
                # The budget ran out, but the JSON may still have closed in
                # time; only retry when it is actually unparseable.
                try:
                    return parse_json_content(content)
                except (LlmError, json.JSONDecodeError):
                    continue
            return parse_json_content(content)
        raise LlmError(
            f"completion still truncated at {max_tokens * 2} tokens (finish_reason=length)"
        )

    def embed(self, session: Session, texts: list[str]) -> list[list[float]]:
        settings = get_settings()
        batches: list[list[str]] = []
        size = 0
        for text in texts:
            length = len(text.encode())
            if length > 32768:
                raise LlmError("single embedding input exceeds the registered input bound")
            if not batches or size + length > 32768:
                batches.append([])
                size = 0
            batches[-1].append(text)
            size += length
        vectors: list[list[float]] = []
        for batch in batches:
            data = self._post(
                session,
                "/embeddings",
                "embedding",
                settings.embedding_model,
                {"model": settings.embedding_model, "input": batch, "dimensions": EMBEDDING_DIM},
            )
            rows = sorted(data["data"], key=lambda r: r["index"])
            if [row["index"] for row in rows] != list(range(len(batch))):
                raise LlmError("embedding response indexes do not match the requested batch")
            vectors.extend(truncate_embedding(list(r["embedding"])) for r in rows)
        return vectors
