"""Explicit, disabled topic synthesis on the shared paid queue; no automatic producer."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from unspun.core.billing import CallContext, UsageUnknown
from unspun.core.billing_models import BudgetPolicy
from unspun.core.config import get_settings
from unspun.core.content import fingerprint
from unspun.core.db import session_scope
from unspun.core.llm import LlmClient
from unspun.core.sources import Source
from unspun.core.synthesis_contracts import (
    KINDS,
    VERSION,
    ManualReview,
    SynthesisDraft,
    SynthesisReview,
    supported,
    synthesis_contract,
    text_contract,
)
from unspun.core.synthesis_models import TopicSynthesis
from unspun.core.synthesis_receipts import call_spec, physical_receipt
from unspun.core.task_models import PipelineTask
from unspun.core.tasks import Lease, enqueue
from unspun.core.topic_contracts import RecordUpdate, SaveDerivation, TopicClaim, TopicMutation
from unspun.core.topic_models import Topic
from unspun.core.topic_synthesis import retained_response_valid, synthesis_input, validate_draft
from unspun.core.topics import derivation_input, mutate_topic
from unspun.pipeline.r1_worker import Blocked, SessionScope


def enqueue_synthesis(
    session: Session,
    topic_id: UUID,
    expected_revision: int,
    reviewer: ManualReview,
    *,
    sources: list[Source],
    now: datetime,
    response_mode: Literal["live", "mock"] = "live",
) -> int | None:
    if not get_settings().r2_synthesis_enabled:
        return None
    request_key = fingerprint(
        [
            str(topic_id),
            expected_revision,
            reviewer.model_dump(mode="json"),
            synthesis_contract(),
            response_mode,
        ]
    )
    existing = session.scalar(
        select(PipelineTask).where(
            PipelineTask.kind == "topic_synthesize",
            PipelineTask.object_key == "topic:" + str(topic_id),
            PipelineTask.payload["request_key"].astext == request_key,
        )
    )
    if existing is not None:
        return existing.id
    packet = synthesis_input(
        session,
        topic_id,
        expected_revision,
        reviewer,
        sources=sources,
        now=now,
        response_mode=response_mode,
    )
    packet["request_key"] = request_key
    return _enqueue(session, "topic_synthesize", packet)


def _enqueue(session: Session, kind: str, packet: dict[str, Any]) -> int:
    content = packet["snapshot"]["members"][0]["input_snapshot"]["content"]
    return enqueue(
        session,
        queue="paid",
        kind=kind,
        object_key="topic:" + packet["topic_id"],
        source_id=content["source_id"],
        input_fingerprint=fingerprint(packet),
        strategy_version=VERSION,
        payload=packet,
        max_attempts=3,
    )


class SynthesisHandler:
    def __init__(
        self,
        sources: dict[str, Source],
        *,
        scope: SessionScope = session_scope,
        client_factory: Callable[[CallContext], LlmClient] | None = None,
        allow_mock: bool = False,
    ) -> None:
        self.sources = list(sources.values())
        self.scope, self.allow_mock = scope, allow_mock
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
            not get_settings().r2_synthesis_enabled
            or lease.kind not in KINDS
            or lease.strategy_version != VERSION
            or lease.payload.get("contract") != synthesis_contract()
            or task is None
            or task.status != "running"
            or task.claim_version != lease.version
            or task.claimed_by != lease.worker
            or task.lease_until is None
            or task.lease_until <= datetime.now(UTC)
            or task.kind != lease.kind
            or task.queue != "paid"
            or task.queue != lease.queue
            or task.source_id != lease.source_id
            or task.article_id != lease.article_id
            or task.strategy_version != lease.strategy_version
            or task.object_key != lease.object_key
            or task.payload != lease.payload
            or task.input_fingerprint != lease.input_fingerprint
            or fingerprint(lease.payload) != lease.input_fingerprint
        ):
            raise Blocked("synthesis is disabled or its task lease/input changed")
        if lease.payload["response_mode"] == "mock":
            policy = session.get(BudgetPolicy, 1)
            if not self.allow_mock or policy is None or policy.scope != "evaluation":
                raise Blocked("mock synthesis requires an explicitly isolated test handler")
        for member in lease.payload["snapshot"]["members"]:
            content = member["input_snapshot"]["content"]
            source = next((s for s in self.sources if s.id == content["source_id"]), None)
            if (
                source is None
                or source.r1 is None
                or not source.r1.allows_paid(content["scope"])
                or not source.r1.publish
            ):
                raise Blocked("synthesis source or material scope is disabled")

    def _validate(self, session: Session, packet: dict[str, Any]) -> None:
        try:
            live = synthesis_input(
                session,
                UUID(packet["topic_id"]),
                packet["expected_revision"],
                ManualReview.model_validate(packet["reviewer"]),
                sources=self.sources,
                now=datetime.now(UTC),
                response_mode=packet["response_mode"],
            )
            if live != {k: packet[k] for k in live}:
                raise ValueError("synthesis dependencies changed")
        except (ValueError, KeyError, TypeError) as error:
            raise Blocked(str(error)) from error

    def _draft(self, session: Session, lease: Lease) -> TopicSynthesis | None:
        if lease.kind == "topic_synthesize":
            return None
        row = session.get(TopicSynthesis, lease.payload["generation_key"], populate_existing=True)
        if (
            row is None
            or row.status != "draft"
            or row.input_fingerprint != fingerprint(row.input_snapshot)
            or row.input_snapshot
            != {
                k: v
                for k, v in lease.payload.items()
                if k not in {"generation_key", "draft_fingerprint"}
            }
            or fingerprint(row.draft) != lease.payload["draft_fingerprint"]
            or not retained_response_valid(session, row, review=False)
        ):
            raise Blocked("synthesis draft or its original input binding changed")
        return row

    def run(self, lease: Lease) -> dict[str, Any]:
        with self.scope() as session:
            self._guard(session, lease)
            self._validate(session, lease.payload)
            row = self._draft(session, lease)
            draft = row.draft if row else None
            engine = session.get_bind().engine
        review = lease.kind == "topic_synthesis_review"
        context = CallContext(
            stage="topic_synthesis_review" if review else "topic_synthesis",
            phase="review" if review else "synthesize",
            logical_key=lease.kind + ":" + lease.input_fingerprint,
            lease=lease,
        )
        try:
            with Session(engine) as session, self.client_factory(context) as client:
                raw = client.chat_json(session, **call_spec(lease, draft))
                if not client.call_ids:
                    raise Blocked("synthesis has no physical response")
                request_id = client.call_ids[-1]
            with self.scope() as session:
                self._guard(session, lease)
                receipt = physical_receipt(session, lease, raw, request_id, draft)
            return {"raw": raw, "receipt": receipt}
        except UsageUnknown as error:
            raise Blocked(str(error)) from error

    def apply(self, session: Session, lease: Lease, result: dict[str, Any]) -> dict[str, Any]:
        self._guard(session, lease)
        row = self._draft(session, lease)
        raw = result["raw"]
        receipt = physical_receipt(
            session, lease, raw, result["receipt"]["request_id"], row.draft if row else None
        )
        if receipt != result["receipt"]:
            raise Blocked("synthesis receipt envelope changed")
        if row is None:
            draft = SynthesisDraft.model_validate(raw)
            validate_draft(session, lease.payload, draft)
            row = TopicSynthesis(
                input_fingerprint=lease.input_fingerprint,
                task_id=lease.task_id,
                topic_id=lease.payload["topic_id"],
                input_snapshot=lease.payload,
                draft=draft.model_dump(mode="json"),
                generation_receipt=receipt,
                response_mode=receipt["response_mode"],
                status="draft",
            )
            session.add(row)
            try:
                self._validate(session, lease.payload)
            except Blocked:
                row.status = "stale"
                return {"status": "stale"}
            if draft.outcome == "abstained":
                row.status = "abstained"
                return {"status": "abstained"}
            return {
                "review_task": _enqueue(
                    session,
                    "topic_synthesis_review",
                    {
                        **lease.payload,
                        "generation_key": row.input_fingerprint,
                        "draft_fingerprint": fingerprint(row.draft),
                    },
                )
            }
        review = SynthesisReview.model_validate(raw)
        row.review, row.review_receipt = review.model_dump(mode="json"), receipt
        draft = SynthesisDraft.model_validate(row.draft)
        if not supported(draft, review):
            row.status = "rejected"
            return {"status": "rejected"}
        session.scalar(
            select(Topic)
            .where(Topic.id == row.topic_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        try:
            self._validate(session, lease.payload)
        except Blocked:
            row.status = "stale"
            return {"status": "stale"}
        validate_draft(session, lease.payload, draft)
        revision = lease.payload["expected_revision"]
        topic_id = UUID(row.topic_id)
        applied: dict[str, Any] = {"updates": [], "derivations": {}}
        for index, item in enumerate(draft.contributions):
            if item.change == "none":
                continue
            assert item.progress_key
            update_id = uuid5(topic_id, item.progress_key)
            change = mutate_topic(
                session,
                topic_id,
                TopicMutation(
                    mutation_id=uuid5(
                        topic_id, row.input_fingerprint + ":progress:" + item.progress_key
                    ),
                    expected_revision=revision,
                    actor="r2-synthesis-worker:" + row.response_mode,
                    reason=item.novelty_basis,
                    change=RecordUpdate(
                        update_id=update_id,
                        summary=item.text,
                        decision_version=VERSION + ":" + item.classification,
                        progress_key=item.progress_key,
                        classification="discussion_focus"
                        if item.classification == "discussion_focus"
                        else "development",
                        attribution=item.attribution,
                        limitations=item.limitations,
                        evidence=item.evidence,
                        occurred=item.occurred,
                        reported=item.reported,
                    ),
                ),
                sources=self.sources,
                now=datetime.now(UTC),
            )
            revision = change.revision
            applied["updates"].append(
                {"update_id": str(update_id), "revision": revision, "contribution_index": index}
            )
        for kind in ("overview", "guide"):
            text_kind: Literal["overview", "guide"] = "overview" if kind == "overview" else "guide"
            token = derivation_input(
                session,
                topic_id,
                text_contract(),
                kind=text_kind,
                sources=self.sources,
                now=datetime.now(UTC),
            )
            change = mutate_topic(
                session,
                topic_id,
                TopicMutation(
                    mutation_id=uuid5(topic_id, row.input_fingerprint + ":" + kind),
                    expected_revision=revision,
                    actor="r2-synthesis-worker:" + row.response_mode,
                    reason="Reviewed synthesis of pinned manual member materials",
                    change=SaveDerivation(
                        kind=text_kind,
                        contract=text_contract(),
                        input_fingerprint=token,
                        claims=tuple(
                            TopicClaim(
                                text=c.text,
                                attribution=c.attribution,
                                limitations=c.limitations,
                                evidence=c.evidence,
                            )
                            for c in getattr(draft, kind)
                        ),
                    ),
                ),
                sources=self.sources,
                now=datetime.now(UTC),
            )
            revision = change.revision
            applied["derivations"][kind] = revision
        row.applied, row.status = applied, "applied"
        return {"status": "applied", "response_mode": row.response_mode, **applied}
