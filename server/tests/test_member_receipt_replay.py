"""Offline protocol projection of exposed real v4 audits, never semantic validation.

Only checks/issues are projected into the new wire schema. Every assertion and
target remains unchanged. Local mock receipts use a new synthetic generation ID;
no original receipt, score, admission or task is written or certified by this test.
"""

import gzip
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from tests.test_billing import BillingDB
from unspun.core.billing import CallContext
from unspun.core.config import get_settings
from unspun.core.content import fingerprint
from unspun.core.llm import LlmClient, parse_json_content
from unspun.core.member_contracts import (
    AUDIT_PROMPTS,
    AuditKind,
    MemberAuditContent,
    MemberDecision,
    member_contract,
)
from unspun.core.member_evidence import audit_packet, audit_targets, review_binding
from unspun.core.member_receipts import audit_from_call
from unspun.core.models import Article
from unspun.core.tasks import claim, enqueue

pytest_plugins = ["tests.test_billing"]
EXPOSED = Path(__file__).resolve().parents[2] / "docs/acceptance/r2-06-grounding"


def exposed(name: str) -> list[dict[str, Any]]:
    return json.loads(gzip.decompress((EXPOSED / name).read_bytes()))


AUDITS = [r for r in exposed("physical-requests.json.gz") if r["stage"] == "topic_review"]


@pytest.mark.parametrize("bill", AUDITS, ids=[r["id"] for r in AUDITS])
def test_real_audit_content_is_receipted_offline_without_semantic_credit(
    billing_db: BillingDB, monkeypatch: pytest.MonkeyPatch, bill: dict[str, Any]
) -> None:
    db = billing_db
    monkeypatch.setenv("UNSPUN_R2_MEMBER_PROCESSING_ENABLED", "true")
    get_settings.cache_clear()
    db.policy(stage_caps={"topic_review": "0.30"})
    task = next(t for t in exposed("tasks.json.gz") if t["id"] == bill["task_id"])
    judgment = next(
        j
        for j in exposed("judgments.json.gz")
        if j["input_fingerprint"] == task["payload"]["decision_key"]
    )
    reconstruction = next(
        r for r in exposed("reconstructed-requests.json.gz") if r["request_id"] == bill["id"]
    )
    assert fingerprint(reconstruction["request"]) == bill["request_fingerprint"]
    kind = cast(AuditKind, reconstruction["kind"])
    historical = parse_json_content(bill["response_payload"]["choices"][0]["message"]["content"])
    with pytest.raises(ValidationError):
        MemberAuditContent.model_validate(historical)  # No runtime legacy-field stripping.
    projection = {k: historical[k] for k in ("checks", "issues")}
    packet: dict[str, Any] = {**deepcopy(task["payload"]), "contract": member_contract()}
    decision = MemberDecision.model_validate(judgment["decision"])
    packet["review_binding"] = review_binding(packet, decision).model_dump(mode="json")
    content = packet["query"]["content"]
    with Session(db.engine) as session, session.begin():
        session.add(
            Article(
                id=content["article_id"],
                source_id=content["source_id"],
                title=content["title"],
                url="https://offline.invalid/" + bill["id"],
            )
        )
        session.flush()
        identity = enqueue(
            session,
            queue="paid",
            kind="topic_review",
            object_key="content:" + str(content["article_id"]),
            article_id=content["article_id"],
            source_id=content["source_id"],
            input_fingerprint=fingerprint(packet),
            strategy_version=str(member_contract()["version"]),
            payload=packet,
        )
        lease = claim(session, queue="paid", kinds={"topic_review"}, worker="offline-replay")
        assert lease and lease.task_id == identity
    calls: list[httpx.Request] = []

    def replay(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        response = deepcopy(bill["response_payload"])
        response["id"] = "offline-replay-" + bill["id"]
        response["choices"][0]["message"]["content"] = json.dumps(projection)
        return httpx.Response(200, json=response)

    context = CallContext(
        stage="topic_review",
        phase="review",
        logical_key=lease.kind + ":" + lease.input_fingerprint + ":" + kind,
        lease=lease,
    )
    with (
        Session(db.engine) as session,
        LlmClient(context=context, transport=httpx.MockTransport(replay)) as client,
    ):
        raw = client.chat_json(
            session,
            model=get_settings().viewpoint_model,
            system=AUDIT_PROMPTS[kind],
            user=json.dumps(audit_packet(packet, decision, kind), ensure_ascii=False),
            purpose="grounding",
            max_tokens=4096,
        )
        result = audit_from_call(session, lease, decision, kind, client.call_ids[-1], raw)
    assert len(calls) == 1
    assert result.binding == review_binding(packet, decision)
    assert [c.model_dump(mode="json") for c in result.checks] == historical["checks"]
    assert list(result.issues) == historical["issues"]
    assert {c.target for c in result.checks} == set(audit_targets(decision, kind))
    assert result.receipt.request_fingerprint == fingerprint(json.loads(calls[0].content))
