"""Explicit, disabled-by-default topic recall, judgment and review on the shared paid queue."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from unspun.core.billing import CallContext
from unspun.core.config import get_settings
from unspun.core.content import fingerprint
from unspun.core.db import session_scope
from unspun.core.llm import LlmClient, LlmError
from unspun.core.member_contracts import (
    AUDIT_KINDS,
    AUDIT_PROMPTS,
    JUDGE_PROMPT,
    AuditKind,
    MemberAudit,
    MemberDecision,
    MemberReview,
    member_contract,
    project_material,
)
from unspun.core.member_evidence import (
    audit_packet,
    audit_supported,
    audit_targets,
    expanded_evidence,
    review_binding,
    review_supported,
)
from unspun.core.member_models import ContentVector, MemberJudgment
from unspun.core.member_recall import (
    current_input,
    recall_plan,
    select_candidates,
    topic_candidate,
    unit_vector,
    validate_decision,
    vector_input,
)
from unspun.core.member_receipts import audit_from_call
from unspun.core.sources import Source
from unspun.core.task_models import PipelineTask
from unspun.core.tasks import Lease, enqueue
from unspun.core.topic_contracts import SetMember, TopicMutation
from unspun.core.topic_models import Topic, TopicMember
from unspun.core.topics import mutate_topic
from unspun.pipeline.r1_worker import Blocked, SessionScope


def _prompt_packet(
    packet: dict[str, Any], draft: dict[str, Any] | None, kind: AuditKind = "complete_basis"
) -> dict[str, Any]:
    if draft is not None:
        return audit_packet(packet, MemberDecision.model_validate(draft), kind)
    topic = packet["candidate"]["topic"]
    return {
        "query": project_material(packet["query"], "query"),
        "candidate": {
            "topic": {
                **topic,
                "anchors": [
                    {**a, "snapshot": project_material(a["snapshot"], "anchor")}
                    for a in topic["anchors"]
                ],
            }
        },
        "output_schema": MemberDecision.model_json_schema(),
    }


def _enabled(sources: list[Source], snapshot: dict[str, Any]) -> None:
    if not get_settings().r2_member_processing_enabled:
        raise Blocked("member processing is disabled")
    content = snapshot["content"]
    source = next((s for s in sources if s.id == content["source_id"]), None)
    if (
        source is None
        or source.discovery_owner != "r1"
        or source.r1 is None
        or not source.r1.allows_paid(content["scope"])
        or not source.r1.publish
    ):
        raise Blocked("member processing source or material scope is disabled")


def _enqueue(session: Session, kind: str, payload: dict[str, Any]) -> int:
    content = payload["query"]["content"]
    return enqueue(
        session,
        queue="paid",
        kind=kind,
        object_key="content:" + str(content["article_id"]),
        article_id=content["article_id"],
        source_id=content["source_id"],
        input_fingerprint=fingerprint(payload),
        strategy_version=str(payload["contract"]["version"]),
        payload=payload,
    )


def enqueue_member_processing(
    session: Session,
    article_id: int,
    *,
    sources: list[Source],
    now: datetime,
    topic_ids: frozenset[str] | None = None,
) -> int | None:
    """An internal explicit entry, never called by reading or the R1 scheduler/card chain."""
    if not get_settings().r2_member_processing_enabled:
        return None
    plan = recall_plan(session, article_id, sources, now, topic_ids=topic_ids)
    _enabled(sources, plan["query"])
    return _enqueue(session, "topic_recall", plan)


class MemberHandler:
    def __init__(
        self,
        sources: dict[str, Source],
        *,
        scope: SessionScope = session_scope,
        client_factory: Callable[[CallContext], LlmClient] | None = None,
        topic_ids: frozenset[str] | None = None,
    ) -> None:
        self.sources = list(sources.values())
        self.topic_ids = topic_ids
        self.scope = scope
        self.client_factory: Callable[[CallContext], LlmClient] = client_factory or (
            lambda context: LlmClient(context=context)
        )

    def _guard(self, session: Session, lease: Lease) -> None:
        task = session.scalar(
            select(PipelineTask)
            .where(PipelineTask.id == lease.task_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            task is None
            or task.status != "running"
            or task.claim_version != lease.version
            or task.claimed_by != lease.worker
            or task.lease_until is None
            or task.lease_until <= datetime.now(UTC)
            or task.kind != lease.kind
            or task.queue != "paid"
            or task.payload != lease.payload
            or task.input_fingerprint != lease.input_fingerprint
            or fingerprint(lease.payload) != lease.input_fingerprint
            or lease.strategy_version != str(member_contract()["version"])
        ):
            raise Blocked("member task lease or immutable input changed")
        _enabled(self.sources, lease.payload["query"])

    def _validate(self, session: Session, packet: dict[str, Any], *, recall: bool = False) -> None:
        now = datetime.now(UTC)
        if packet["contract"] != member_contract():
            raise Blocked("member contract changed")
        try:
            query = current_input(
                session, packet["query"]["content"]["article_id"], self.sources, now
            )
            if fingerprint(query) != fingerprint(packet["query"]):
                raise ValueError("content input changed")
            _enabled(self.sources, query)
            if recall:
                if fingerprint(
                    recall_plan(
                        session,
                        query["content"]["article_id"],
                        self.sources,
                        now,
                        topic_ids=self.topic_ids,
                    )
                ) != fingerprint(packet):
                    raise ValueError("recall candidates changed")
            else:
                candidate = packet["candidate"]["topic"]
                if self.topic_ids is not None and candidate["id"] not in self.topic_ids:
                    raise ValueError("candidate is outside the registered topic pool")
                live = topic_candidate(session, candidate["id"], self.sources, now)
                if fingerprint(live) != fingerprint(candidate):
                    raise ValueError("candidate input changed")
                expected = [fingerprint(vector_input(query))] + [
                    fingerprint(vector_input(a["snapshot"])) for a in live["anchors"]
                ]
                if packet["candidate"]["vectors"] != expected:
                    raise ValueError("candidate vector versions changed")
                for key in expected:
                    row = session.get(ContentVector, key, populate_existing=True)
                    if row is None or fingerprint(row.input_snapshot) != key:
                        raise ValueError("candidate vector is missing or invalid")
        except (ValueError, KeyError, TypeError) as error:
            raise Blocked(str(error)) from error

    def _vector(self, lease: Lease, snapshot: dict[str, Any]) -> list[float]:
        version = vector_input(snapshot)
        key, dimensions = fingerprint(version), int(version["dimensions"])
        with self.scope() as session:
            self._guard(session, lease)
            _enabled(self.sources, snapshot)
            if fingerprint(
                current_input(
                    session, snapshot["content"]["article_id"], self.sources, datetime.now(UTC)
                )
            ) != fingerprint(snapshot):
                raise Blocked("embedding material changed")
            row = session.get(ContentVector, key)
            if row is not None:
                if (
                    row.model != version["model"]
                    or row.dimensions != dimensions
                    or row.input_snapshot != version
                ):
                    raise Blocked("embedding version is invalid")
                return unit_vector(row.vector, dimensions)
            engine = session.get_bind().engine
        with (
            Session(engine) as session,
            self.client_factory(
                CallContext(
                    stage="topic_embedding", phase="embed", logical_key="vector:" + key, lease=lease
                )
            ) as client,
        ):
            values = client.embed(session, [version["text"]])
            if len(values) != 1:
                raise ValueError("embedding response must contain one vector")
            vector = unit_vector(values[0], dimensions)
            call_ids = client.call_ids.copy()
        with self.scope() as session:
            self._guard(session, lease)
            current = current_input(
                session, snapshot["content"]["article_id"], self.sources, datetime.now(UTC)
            )
            if fingerprint(current) != fingerprint(snapshot):
                raise Blocked("embedding input changed before checkpoint")
            session.execute(
                insert(ContentVector)
                .values(
                    input_fingerprint=key,
                    article_id=snapshot["content"]["article_id"],
                    material_id=snapshot["content"]["material_id"],
                    model=version["model"],
                    dimensions=dimensions,
                    contract_version=version["version"],
                    input_snapshot=version,
                    vector=vector,
                    call_ids=call_ids,
                )
                .on_conflict_do_nothing(index_elements=[ContentVector.input_fingerprint])
            )
        return vector

    def run(self, lease: Lease) -> dict[str, Any]:
        with self.scope() as session:
            self._guard(session, lease)
            self._validate(session, lease.payload, recall=lease.kind == "topic_recall")
            engine = session.get_bind().engine
            row = (
                session.get(MemberJudgment, lease.payload["decision_key"])
                if lease.kind == "topic_review"
                else None
            )
            if row is not None and (
                row.input_snapshot
                != {k: lease.payload[k] for k in ("query", "candidate", "contract")}
                or fingerprint(row.input_snapshot) != row.input_fingerprint
            ):
                raise Blocked("review original packet binding changed")
            draft = row.decision if row is not None else None
            if lease.kind == "topic_review" and (
                draft is None or fingerprint(draft) != lease.payload["decision_fingerprint"]
            ):
                raise Blocked("review decision changed or is missing")
        if lease.kind == "topic_recall":
            plan = lease.payload
            if not plan["topics"]:
                return {"candidates": []}
            snapshots = [plan["query"]] + [
                a["snapshot"] for t in plan["topics"] for a in t["anchors"]
            ]
            vectors = {fingerprint(vector_input(s)): self._vector(lease, s) for s in snapshots}
            return {"candidates": select_candidates(plan, vectors)}
        if draft is not None:
            decision = MemberDecision.model_validate(draft)
            binding = review_binding(lease.payload, decision)
            if lease.payload.get("review_binding") != binding.model_dump(mode="json"):
                raise Blocked("review binding changed or is missing")
            audits: list[MemberAudit] = []
            for kind in AUDIT_KINDS:
                with self.scope() as session:
                    self._guard(session, lease)
                    self._validate(session, lease.payload)
                    live = session.get(
                        MemberJudgment, lease.payload["decision_key"], populate_existing=True
                    )
                    if live is None or fingerprint(live.decision) != binding.decision_fingerprint:
                        raise Blocked("review decision changed between audits")
                    validate_decision(session, lease.payload, decision)
                context = CallContext(
                    stage="topic_review",
                    phase="review",
                    logical_key=lease.kind + ":" + lease.input_fingerprint + ":" + kind,
                    lease=lease,
                )
                with Session(engine) as session, self.client_factory(context) as client:
                    raw = client.chat_json(
                        session,
                        model=get_settings().viewpoint_model,
                        system=AUDIT_PROMPTS[kind],
                        user=json.dumps(
                            _prompt_packet(lease.payload, draft, kind), ensure_ascii=False
                        ),
                        purpose="grounding",
                        max_tokens=4096,
                    )
                    if not client.call_ids:
                        raise Blocked("audit has no physical call receipt")
                    call_id = client.call_ids[-1]
                with self.scope() as session:
                    self._guard(session, lease)
                    self._validate(session, lease.payload)
                    live = session.get(
                        MemberJudgment, lease.payload["decision_key"], populate_existing=True
                    )
                    if live is None or fingerprint(live.decision) != binding.decision_fingerprint:
                        raise Blocked("review decision changed during audit")
                    audit = audit_from_call(session, lease, decision, kind, call_id, raw)
                audits.append(audit)
                if audit.kind != kind or not audit_supported(
                    audit, binding, audit_targets(decision, kind)
                ):
                    break
            return {
                "review": MemberReview(binding=binding, audits=tuple(audits)).model_dump(
                    mode="json"
                )
            }
        context = CallContext(
            stage="topic_judgment",
            phase="judge",
            logical_key=lease.kind + ":" + lease.input_fingerprint,
            lease=lease,
        )
        with Session(engine) as session, self.client_factory(context) as client:
            raw = client.chat_json(
                session,
                model=get_settings().summary_model,
                system=JUDGE_PROMPT,
                user=json.dumps(_prompt_packet(lease.payload, None), ensure_ascii=False),
                purpose="topic_judgment",
                max_tokens=4096,
            )
        return {"decision": MemberDecision.model_validate(raw).model_dump(mode="json")}

    def apply(self, session: Session, lease: Lease, result: dict[str, Any]) -> dict[str, Any]:
        self._guard(session, lease)
        packet = lease.payload
        if lease.kind == "topic_recall":
            self._validate(session, packet, recall=True)
            tasks = [
                _enqueue(
                    session,
                    "topic_judge",
                    {"query": packet["query"], "candidate": c, "contract": packet["contract"]},
                )
                for c in result["candidates"]
            ]
            return {"judgment_tasks": tasks, "independent": not tasks}
        if lease.kind == "topic_judge":
            self._validate(session, packet)
            decision = MemberDecision.model_validate(result["decision"])
            validate_decision(session, packet, decision)
            topic = packet["candidate"]["topic"]
            row = MemberJudgment(
                input_fingerprint=lease.input_fingerprint,
                task_id=lease.task_id,
                article_id=lease.article_id,
                topic_id=topic["id"],
                topic_revision=topic["revision"],
                input_snapshot=packet,
                decision=decision.model_dump(mode="json"),
                status="draft" if decision.associated else "independent",
            )
            session.add(row)
            session.flush()
            if not decision.associated:
                return {"decision": row.input_fingerprint, "independent": True}
            review = {
                **packet,
                "decision_key": row.input_fingerprint,
                "decision_fingerprint": fingerprint(row.decision),
                "review_binding": review_binding(packet, decision).model_dump(mode="json"),
            }
            return {"review_task": _enqueue(session, "topic_review", review)}
        row = session.get(MemberJudgment, packet["decision_key"], with_for_update=True)
        if row is None or fingerprint(row.decision) != packet["decision_fingerprint"]:
            raise Blocked("review decision changed or is missing")
        if (
            row.input_snapshot != {k: packet[k] for k in ("query", "candidate", "contract")}
            or fingerprint(row.input_snapshot) != row.input_fingerprint
        ):
            raise Blocked("review original packet binding changed")
        if row.status != "draft":
            return {"status": row.status, "revision": row.applied_revision}
        review = MemberReview.model_validate(result["review"])
        row.review = review.model_dump(mode="json")
        decision = MemberDecision.model_validate(row.decision)
        if not review_supported(packet, decision, review):
            row.status = "rejected"
            return {"status": row.status}
        for audit in review.audits:
            try:
                original = audit_from_call(
                    session,
                    lease,
                    decision,
                    audit.kind,
                    audit.receipt.request_id,
                    {
                        "checks": [c.model_dump(mode="json") for c in audit.checks],
                        "issues": list(audit.issues),
                    },
                )
            except (LlmError, ValueError):
                row.status = "rejected"
                return {"status": row.status}
            if audit != original:
                row.status = "rejected"
                return {"status": row.status}
        topic = session.scalar(
            select(Topic)
            .where(Topic.id == row.topic_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        try:
            self._validate(session, packet)
        except Blocked:
            row.status = "stale"
            return {"status": row.status}
        if (
            topic is None
            or topic.revision != row.topic_revision
            or session.get(TopicMember, (row.topic_id, row.article_id), populate_existing=True)
            is not None
        ):
            row.status = "stale"
            return {"status": row.status}
        decision = MemberDecision.model_validate(row.decision)
        validate_decision(session, packet, decision)
        if not decision.associated:
            row.status = "independent"
            return {"status": row.status}
        self._guard(session, lease)
        receipt = mutate_topic(
            session,
            UUID(row.topic_id),
            TopicMutation(
                mutation_id=uuid5(NAMESPACE_URL, "unspun-member:" + row.input_fingerprint),
                expected_revision=row.topic_revision,
                actor="r2-member-worker",
                reason=decision.basis,
                change=SetMember(
                    article_id=row.article_id,
                    material_id=packet["query"]["content"]["material_id"],
                    relation=cast(
                        Literal["report", "background", "opinion", "explanation", "reprint"],
                        {"same_event": "report", "same_issue": "report"}.get(
                            decision.classification, decision.classification
                        ),
                    ),
                    basis=decision.basis,
                    decision_version=fingerprint(packet["contract"]),
                    evidence=tuple(
                        r
                        for r in expanded_evidence(packet, decision)
                        if r.article_id == row.article_id
                    ),
                ),
            ),
            sources=self.sources,
            now=datetime.now(UTC),
        )
        row.status, row.applied_revision = "applied", receipt.revision
        return {"status": row.status, "revision": receipt.revision}
