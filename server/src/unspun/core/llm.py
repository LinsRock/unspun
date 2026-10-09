"""Thin OpenRouter client; every call records tokens and cost in llm_usage."""

import json
import math
from typing import Any, Protocol

import httpx
from sqlalchemy.orm import Session

from unspun.core.config import get_settings
from unspun.core.models import EMBEDDING_DIM, LlmUsage

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
    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
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

    def __enter__(self) -> "LlmClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _record(self, session: Session, purpose: str, model: str, usage: dict[str, Any]) -> None:
        session.add(
            LlmUsage(
                purpose=purpose,
                model=model,
                prompt_tokens=int(usage.get("prompt_tokens") or 0),
                completion_tokens=int(usage.get("completion_tokens") or 0),
                cost_usd=float(usage.get("cost") or 0.0),
            )
        )

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
            resp = self._client.post(
                "/chat/completions",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "response_format": {"type": "json_object"},
                    "usage": {"include": True},
                    "max_tokens": attempt_max_tokens,
                },
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            self._record(session, purpose, model, data.get("usage") or {})
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
        resp = self._client.post(
            "/embeddings",
            json={
                "model": settings.embedding_model,
                "input": texts,
                "dimensions": EMBEDDING_DIM,
            },
        )
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        self._record(session, "embedding", settings.embedding_model, data.get("usage") or {})
        rows = sorted(data["data"], key=lambda r: r["index"])
        if len(rows) != len(texts):
            raise LlmError(f"asked for {len(texts)} embeddings, got {len(rows)}")
        return [truncate_embedding(list(r["embedding"])) for r in rows]
