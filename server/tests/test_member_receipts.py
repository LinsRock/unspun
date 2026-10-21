"""Physical audit association faults; no live provider requests."""

import json
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from tests.test_member_grounding import judged
from tests.test_member_processing import MemberDB
from unspun.core.billing_models import BilledRequest
from unspun.core.llm import LlmClient, LlmError
from unspun.core.member_contracts import MemberAuditContent, MemberDecision
from unspun.core.member_receipts import audit_from_call
from unspun.core.task_models import PipelineTask
from unspun.core.tasks import fail
from unspun.core.topic_models import TopicMember
from unspun.pipeline.member_processing import MemberHandler
from unspun.pipeline.r1_worker import Blocked

pytest_plugins = ["tests.test_member_processing"]


@pytest.mark.parametrize("field", ["kind", "binding", "receipt", "approved", "revised_decision"])
def test_wire_schema_never_accepts_model_association_fields(field: str) -> None:
    raw: dict[str, Any] = {
        "checks": [{"target": "query_facts/0", "status": "supported", "issues": []}],
        "issues": [],
        field: {},
    }
    with pytest.raises(ValidationError):
        MemberAuditContent.model_validate(raw)


@pytest.mark.parametrize(
    "field",
    ["request_id", "request_fingerprint", "response_fingerprint", "lease_fingerprint"],
)
def test_receipt_substitution_cannot_authorize_cas(member_db: MemberDB, field: str) -> None:
    db = member_db
    judged(db)
    lease = db.claim("topic_review")
    result = db.handler().run(lease)
    result["review"]["audits"][0]["receipt"][field] = (
        result["review"]["audits"][1]["receipt"][field] if field == "request_id" else "0" * 64
    )
    assert db.finish(lease, result)
    assert db.judgment().status == "rejected"
    with db.scope() as session:
        assert session.get(TopicMember, (str(db.topic), db.article)) is None


@pytest.mark.parametrize("field", ["request_fingerprint", "logical_key", "task_attempt_id"])
def test_stale_or_mismatched_cached_call_is_rejected_before_binding(
    member_db: MemberDB, field: str
) -> None:
    db = member_db
    judged(db)
    lease = db.claim("topic_review")
    first = db.handler().run(lease)
    identity = first["review"]["audits"][0]["receipt"]["request_id"]
    before = len(db.calls)

    # Simulate a cache returning an unrelated persisted response, without network.
    class WrongCache(LlmClient):
        def chat_json(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            self.call_ids.append(identity)
            with db.scope() as session:
                row = session.get(BilledRequest, identity)
                assert row and row.response_payload
                return json.loads(row.response_payload["choices"][0]["message"]["content"])

    with db.scope() as session:
        row = session.get(BilledRequest, identity)
        assert row
        setattr(row, field, None if field == "task_attempt_id" else "0" * 64)
    handler = MemberHandler(
        {s.id: s for s in db.sources},
        scope=db.scope,
        client_factory=lambda context: WrongCache(
            context=context, transport=httpx.MockTransport(db.transport)
        ),
    )
    with pytest.raises(LlmError, match="audit"):
        handler.run(lease)
    assert len(db.calls) == before and db.judgment().review is None


def test_raw_response_cannot_be_stamped_with_current_binding(member_db: MemberDB) -> None:
    db = member_db
    judged(db)
    lease = db.claim("topic_review")

    class MixedResponse(LlmClient):
        def chat_json(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            raw = super().chat_json(*args, **kwargs)
            raw["checks"][0]["issues"] = ["Response from another packet"]
            return raw

    handler = MemberHandler(
        {s.id: s for s in db.sources},
        scope=db.scope,
        client_factory=lambda context: MixedResponse(
            context=context, transport=httpx.MockTransport(db.transport)
        ),
    )
    with pytest.raises(LlmError, match="differs from its physical response"):
        handler.run(lease)
    assert db.judgment().review is None


def test_same_attempt_cache_is_verified_but_new_lease_replay_is_rejected(
    member_db: MemberDB,
) -> None:
    db = member_db
    judged(db)
    lease = db.claim("topic_review")
    first = db.handler().run(lease)
    before = len(db.calls)
    assert db.handler().run(lease) == first
    assert len(db.calls) == before
    with db.scope() as session:
        task = session.get(PipelineTask, lease.task_id)
        assert task and task.max_attempts == 1
        # Fault injection only: force a second lease to exercise the independent
        # physical-attempt fence, despite the normal single-attempt policy.
        task.max_attempts = 2
        fail(
            session,
            lease,
            error="synthetic worker loss",
            now=datetime.now(UTC) - timedelta(minutes=2),
        )
    current = db.claim("topic_review")
    assert current.attempt_id != lease.attempt_id
    with pytest.raises(Blocked, match="lease"):
        db.handler().run(current)
    receipt = first["review"]["audits"][0]
    with db.scope() as session, pytest.raises(LlmError, match="current settled request and lease"):
        audit_from_call(
            session,
            current,
            MemberDecision.model_validate(db.judgment().decision),
            "query_support",
            receipt["receipt"]["request_id"],
            {k: receipt[k] for k in ("checks", "issues")},
        )
    assert len(db.calls) == before
    with pytest.raises(Blocked, match="lease"):
        db.finish(current, deepcopy(first))
    assert db.judgment().status == "draft"


def test_late_http_response_stays_billed_without_creating_an_envelope(member_db: MemberDB) -> None:
    db = member_db
    judged(db)
    lease = db.claim("topic_review")

    def late(request: httpx.Request) -> httpx.Response:
        response = db.transport(request)
        with db.scope() as session:
            task = session.get(PipelineTask, lease.task_id)
            assert task
            task.lease_until = datetime.now(UTC) - timedelta(seconds=1)
        return response

    handler = MemberHandler(
        {s.id: s for s in db.sources},
        scope=db.scope,
        client_factory=lambda context: LlmClient(
            context=context, transport=httpx.MockTransport(late)
        ),
    )
    with pytest.raises(Blocked, match="lease"):
        handler.run(lease)
    assert db.judgment().review is None
    assert db.billing.requests()[-1].status == "responded"
    with pytest.raises(Blocked, match="lease"):
        handler.run(replace(lease, version=lease.version + 1))


def test_durable_response_tamper_after_run_is_rejected_at_cas(member_db: MemberDB) -> None:
    db = member_db
    judged(db)
    lease = db.claim("topic_review")
    result = db.handler().run(lease)
    with db.scope() as session:
        row = session.get(BilledRequest, result["review"]["audits"][0]["receipt"]["request_id"])
        assert row and row.response_payload
        payload = deepcopy(row.response_payload)
        payload["extra"] = "different physical response"
        row.response_payload = payload
    assert db.finish(lease, result)
    assert db.judgment().status == "rejected"


def test_changed_packet_cannot_rebind_an_actual_response(member_db: MemberDB) -> None:
    db = member_db
    judged(db)
    lease = db.claim("topic_review")
    result = db.handler().run(lease)
    audit = result["review"]["audits"][0]
    packet = deepcopy(lease.payload)
    packet["query"]["content"]["paragraphs"][0]["text"] += " Changed original."
    with db.scope() as session, pytest.raises(LlmError, match="fingerprint or cache"):
        audit_from_call(
            session,
            replace(lease, payload=packet),
            MemberDecision.model_validate(db.judgment().decision),
            "query_support",
            audit["receipt"]["request_id"],
            {"checks": audit["checks"], "issues": audit["issues"]},
        )


def test_provider_generation_replay_between_calls_is_rejected(member_db: MemberDB) -> None:
    db = member_db
    judged(db)
    lease = db.claim("topic_review")
    result = db.handler().run(lease)
    with db.scope() as session:
        first, second = [
            session.get(BilledRequest, a["receipt"]["request_id"])
            for a in result["review"]["audits"][:2]
        ]
        assert first and second and second.response_payload
        payload = deepcopy(second.response_payload)
        payload["id"] = first.provider_generation_id
        second.provider_generation_id = first.provider_generation_id
        second.response_payload = payload
    assert db.finish(lease, result)
    assert db.judgment().status == "rejected"
