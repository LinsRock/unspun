"""Bind both generation and semantic review to persisted physical responses."""

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from unspun.core.billing import provider_cap
from unspun.core.billing_models import BilledRequest
from unspun.core.config import get_settings
from unspun.core.content import fingerprint
from unspun.core.llm import LlmError, chat_request, parse_json_content
from unspun.core.synthesis_contracts import GENERATE_PROMPT, MAX_BYTES, MAX_TOKENS, REVIEW_PROMPT
from unspun.core.task_models import TaskAttempt
from unspun.core.tasks import Lease
from unspun.core.topic_synthesis import prompt_packet


def call_spec(lease: Lease, draft: dict[str, Any] | None) -> dict[str, Any]:
    review = lease.kind == "topic_synthesis_review"
    return {
        "model": get_settings().viewpoint_model if review else get_settings().summary_model,
        "system": REVIEW_PROMPT if review else GENERATE_PROMPT,
        "user": json.dumps(prompt_packet(lease.payload, draft), ensure_ascii=False),
        "purpose": "grounding" if review else "topic_synthesis",
        "max_tokens": MAX_TOKENS,
    }


def physical_receipt(
    session: Session,
    lease: Lease,
    raw: dict[str, Any],
    request_id: str,
    draft: dict[str, Any] | None,
) -> dict[str, Any]:
    """Current lease is checked by caller. Exact cached responses can recover the same task.

    A recovered response retains its original attempt ID; it is never restamped as
    a fresh call. Another task, input, model or response cannot borrow the receipt.
    """
    review = lease.kind == "topic_synthesis_review"
    stage, phase = (
        ("topic_synthesis_review", "review") if review else ("topic_synthesis", "synthesize")
    )
    spec = call_spec(lease, draft)
    expected = {**chat_request(**spec), "provider": provider_cap(spec["model"])}
    logical = fingerprint(
        [
            lease.kind + ":" + lease.input_fingerprint,
            phase,
            spec["purpose"],
            spec["model"],
            expected,
        ]
    )
    row = session.get(BilledRequest, request_id, populate_existing=True)
    if row is None:
        raise LlmError("synthesis has no physical receipt")
    original_attempt = session.get(TaskAttempt, row.task_attempt_id, populate_existing=True)
    if (
        row.task_id != lease.task_id
        or original_attempt is None
        or original_attempt.task_id != lease.task_id
        or original_attempt.claim_version > lease.version
        or row.object_key != lease.object_key
        or row.article_id != lease.article_id
        or row.source_id != lease.source_id
        or (row.stage, row.phase, row.purpose, row.model)
        != (stage, phase, spec["purpose"], spec["model"])
        or row.request_fingerprint != fingerprint(expected)
        or row.logical_key != logical
        or row.status != "responded"
        or row.usage_id is None
        or row.http_status is None
        or not 200 <= row.http_status < 300
        or not row.provider_generation_id
        or row.response_payload is None
        or row.provider_generation_id != row.response_payload.get("id")
    ):
        raise LlmError("synthesis physical request does not match the registered task")
    if (
        session.scalar(
            select(BilledRequest.id)
            .where(
                BilledRequest.provider_generation_id == row.provider_generation_id,
                BilledRequest.id != row.id,
            )
            .limit(1)
        )
        is not None
    ):
        raise LlmError("synthesis provider response was replayed across requests")
    try:
        choice = row.response_payload["choices"][0]
        content = choice["message"]["content"]
        if (
            choice.get("finish_reason") != "stop"
            or not isinstance(content, str)
            or len(content.encode()) > MAX_BYTES
        ):
            raise LlmError("synthesis response did not complete within its registered bounds")
        original = parse_json_content(content)
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise LlmError("synthesis response has no valid physical content") from error
    if fingerprint(original) != fingerprint(raw):
        raise LlmError("synthesis content differs from its physical response")
    mode = "mock" if row.response_payload.get("unspun_mock") is True else "live"
    if lease.payload["response_mode"] != mode:
        raise LlmError("synthesis response mode differs from the explicit registration")
    return {
        "request_id": row.id,
        "original_attempt_id": row.task_attempt_id,
        "request_fingerprint": row.request_fingerprint,
        "response_fingerprint": fingerprint(row.response_payload),
        "response_mode": mode,
        "input_fingerprint": lease.input_fingerprint,
    }
