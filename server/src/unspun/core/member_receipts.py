"""Associate audit content only through the persisted physical request and lease."""

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from unspun.core.billing import provider_cap
from unspun.core.billing_models import BilledRequest
from unspun.core.config import get_settings
from unspun.core.content import fingerprint
from unspun.core.llm import LlmError, chat_request, parse_json_content
from unspun.core.member_contracts import (
    AUDIT_PROMPTS,
    MEMBER_OUTPUT_BYTES,
    AuditKind,
    AuditReceipt,
    MemberAudit,
    MemberAuditContent,
    MemberDecision,
    member_contract,
)
from unspun.core.member_evidence import audit_packet, review_binding
from unspun.core.task_models import TaskAttempt
from unspun.core.tasks import Lease


def audit_from_call(
    session: Session,
    lease: Lease,
    decision: MemberDecision,
    kind: AuditKind,
    request_id: str,
    raw: dict[str, Any],
) -> MemberAudit:
    """Fail closed before creating an internal envelope; never stamp arbitrary JSON.

    The caller checks the live task/material fence in the same transaction. The
    stored call must match this exact audit request, attempt and returned content.
    A cache hit from another attempt is deliberately not a new lease's receipt.
    """
    row = session.get(BilledRequest, request_id, populate_existing=True)
    attempt = session.get(TaskAttempt, lease.attempt_id, populate_existing=True)
    model = get_settings().viewpoint_model
    if (
        lease.strategy_version != member_contract()["version"]
        or lease.payload.get("contract") != member_contract()
        or row is None
        or attempt is None
        or attempt.task_id != lease.task_id
        or attempt.claim_version != lease.version
        or attempt.worker != lease.worker
        or attempt.status != "running"
        or attempt.lease_until <= datetime.now(UTC)
        or row.task_id != lease.task_id
        or row.task_attempt_id != lease.attempt_id
        or row.article_id != lease.article_id
        or row.source_id != lease.source_id
        or row.object_key != lease.object_key
        or (row.stage, row.phase, row.purpose, row.model)
        != ("topic_review", "review", "grounding", model)
        or row.status != "responded"
        or row.usage_id is None
        or row.http_status is None
        or not 200 <= row.http_status < 300
        or row.response_payload is None
        or not row.provider_generation_id
        or row.provider_generation_id != row.response_payload.get("id")
    ):
        raise LlmError("audit call does not belong to the current settled request and lease")
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
        raise LlmError("audit provider response is replayed across physical requests")
    logical_key = lease.kind + ":" + lease.input_fingerprint + ":" + kind
    # v6 has one physical output size; an old retry cannot become a new receipt.
    expected = [
        {
            **chat_request(
                model=model,
                system=AUDIT_PROMPTS[kind],
                user=json.dumps(audit_packet(lease.payload, decision, kind), ensure_ascii=False),
                purpose="grounding",
                max_tokens=size,
            ),
            "provider": provider_cap(model),
        }
        for size in (4096,)
    ]
    if not any(
        row.request_fingerprint == fingerprint(request)
        and row.logical_key == fingerprint([logical_key, "review", "grounding", model, request])
        for request in expected
    ):
        raise LlmError("audit request fingerprint or cache association does not match")
    try:
        choice = row.response_payload["choices"][0]
        content_text = choice["message"]["content"]
        if (
            choice.get("finish_reason") != "stop"
            or not isinstance(content_text, str)
            or len(content_text.encode()) > MEMBER_OUTPUT_BYTES
        ):
            raise LlmError("audit response exceeds or did not complete within registered bounds")
        original = parse_json_content(content_text)
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise LlmError("audit physical response has no valid content") from error
    if fingerprint(original) != fingerprint(raw):
        raise LlmError("audit content differs from its physical response")
    content = MemberAuditContent.model_validate(original)
    return MemberAudit(
        **content.model_dump(mode="json"),
        kind=kind,
        binding=review_binding(lease.payload, decision),
        receipt=AuditReceipt(
            request_id=row.id,
            request_fingerprint=row.request_fingerprint,
            response_fingerprint=fingerprint(row.response_payload),
            lease_fingerprint=fingerprint(
                [
                    lease.task_id,
                    lease.attempt_id,
                    lease.version,
                    lease.worker,
                    lease.input_fingerprint,
                    lease.strategy_version,
                ]
            ),
        ),
    )
