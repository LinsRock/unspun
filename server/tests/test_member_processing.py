"""Isolated shared-queue processing with real leases/accounting and mocked external HTTP."""

import json
import os
import subprocess
import sys
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Barrier
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from tests.test_billing import BillingDB
from tests.test_content_feed import ready
from tests.test_topics import DEFINITION, member, write
from unspun.core.billing import (
    STAGE_CAPS,
    TOPIC_STAGE_CAPS,
    CallContext,
)
from unspun.core.config import Settings, get_settings
from unspun.core.content import fingerprint
from unspun.core.content_publication import qualified_item
from unspun.core.llm import LlmClient, LlmError
from unspun.core.member_contracts import MemberDecision
from unspun.core.member_models import ContentVector, MemberJudgment
from unspun.core.member_recall import (
    CANDIDATES,
    EMBED_TOPICS,
    current_input,
    recall_plan,
    unit_vector,
    validate_decision,
    vector_input,
)
from unspun.core.models import EMBEDDING_DIM, Article, ContentDerivation, ContentMaterial
from unspun.core.sources import Source, load_sources
from unspun.core.task_models import PipelineTask
from unspun.core.tasks import Lease, claim, complete, reap_expired
from unspun.core.topic_models import Topic, TopicChange, TopicMember
from unspun.pipeline.member_processing import MemberHandler, enqueue_member_processing
from unspun.pipeline.r1_runtime import build_runtime
from unspun.pipeline.r1_worker import Blocked, process_one

pytest_plugins = ["tests.test_billing"]


def decision_for_prompt(
    packet: dict[str, Any], classification: str = "same_event", certainty: str = "certain"
) -> dict[str, Any]:
    # Deliberately synthetic role support; this fixture tests protocol, never semantics.
    facts: list[dict[str, Any]] = []
    for material in [packet["query"], packet["candidate"]["topic"]["anchors"][0]["snapshot"]]:
        paragraph = material["content"]["paragraphs"][0]
        role = {"status": "known", "spans": [{"citation_index": 0, "start": 0, "end": 8}]}
        facts.append(
            {
                "citations": [
                    {
                        "reference_id": paragraph["references"][0]["reference_id"],
                        "quote": paragraph["text"],
                        "start": 0,
                        "end": len(paragraph["text"]),
                    }
                ],
                **{
                    name: role
                    for name in ("subject", "action", "object", "location", "attribution")
                },
                "time": {**role, "role": "occurrence", "precision": "relative"},
            }
        )
    identity = {
        "same_event": "same_occurrence",
        "same_issue": "same_issue",
        "independent": "none",
    }.get(classification, "related")
    reason = {
        "same_event": "same_occurrence",
        "same_issue": "same_issue",
        "background": "context",
        "opinion": "assessment",
        "explanation": "explanation",
        "reprint": "provenance",
        "independent": "none",
    }[classification]
    return {
        "identity": identity,
        "contribution": "report"
        if classification in ("same_event", "same_issue")
        else "none"
        if classification == "independent"
        else classification,
        "certainty": certainty,
        "query_facts": [facts[0]],
        "anchor_facts": [facts[1]],
        "relation": {
            "reason": reason,
            "query_fact_indices": [0],
            "anchor_fact_indices": [0],
            "time": "compatible",
        },
    }


@dataclass
class MemberDB:
    billing: BillingDB
    sources: list[Source]
    article: int
    anchor: int
    topic: UUID
    classification: str = "same_event"
    certainty: str = "certain"
    approved: bool = True
    issues: list[str] = field(default_factory=list[str])
    unknown: bool = False
    truncate: bool = False
    calls: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])

    @contextmanager
    def scope(self) -> Generator[Session]:
        with Session(self.billing.engine) as session, session.begin():
            yield session

    def transport(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        self.calls.append(payload)
        cost = {"cost": "0.00001", "prompt_tokens": 10, "completion_tokens": 5}
        if self.unknown:
            raise httpx.ReadTimeout("synthetic timeout")
        if request.url.path.endswith("embeddings"):
            data = {
                "data": [{"index": 0, "embedding": [1.0] + [0.0] * (EMBEDDING_DIM - 1)}],
                "usage": cost,
            }
        else:
            packet = json.loads(payload["messages"][1]["content"])
            if "kind" in packet:
                out = {
                    "checks": [
                        {
                            "target": target,
                            "status": "supported" if self.approved else "unsupported",
                            "issues": [] if self.approved else ["synthetic unsupported claim"],
                        }
                        for target in packet["targets"]
                    ],
                    "issues": self.issues,
                }
            else:
                out = decision_for_prompt(packet, self.classification, self.certainty)
            data = {
                "choices": [
                    {
                        "finish_reason": "length" if self.truncate else "stop",
                        "message": {"content": "{" if self.truncate else json.dumps(out)},
                    }
                ],
                "usage": cost,
            }
            self.truncate = False
        return httpx.Response(200, json={"id": "synthetic-" + uuid4().hex, **data})

    def handler(self) -> MemberHandler:
        return MemberHandler(
            {s.id: s for s in self.sources},
            scope=self.scope,
            client_factory=lambda context: LlmClient(
                context=context, transport=httpx.MockTransport(self.transport)
            ),
        )

    def enqueue(self) -> int:
        with self.scope() as session:
            task = enqueue_member_processing(
                session, self.article, sources=self.sources, now=datetime.now(UTC)
            )
            assert task
            return task

    def claim(self, kind: str) -> Lease:
        with self.scope() as session:
            lease = claim(
                session, queue="paid", kinds={kind}, worker="synthetic-worker", lease_seconds=900
            )
            assert lease
            return lease

    def finish(self, lease: Lease, out: dict[str, Any]) -> bool:
        with self.scope() as session:
            return complete(session, lease, apply=lambda db: self.handler().apply(db, lease, out))

    def step(self, kind: str) -> tuple[Lease, dict[str, Any]]:
        lease = self.claim(kind)
        out = self.handler().run(lease)
        assert self.finish(lease, out)
        return lease, out

    def judgment(self) -> MemberJudgment:
        with self.scope() as session:
            row = session.scalar(
                select(MemberJudgment).where(MemberJudgment.article_id == self.article)
            )
            assert row
            session.expunge(row)
            return row


@pytest.fixture
def member_db(billing_db: BillingDB, monkeypatch: pytest.MonkeyPatch) -> Generator[MemberDB]:
    monkeypatch.setenv("UNSPUN_R2_MEMBER_PROCESSING_ENABLED", "true")
    get_settings.cache_clear()
    billing_db.policy(stage_caps=TOPIC_STAGE_CAPS.copy())
    source = next(s for s in load_sources() if s.id == "xinhua")
    assert source.r1
    sources = [
        source.model_copy(
            update={
                "discovery_owner": "r1",
                "legacy_enabled": False,
                "r1": source.r1.model_copy(
                    update={
                        "paid": True,
                        "publish": True,
                        "paid_scopes": None,
                        "publish_scopes": None,
                    }
                ),
            }
        )
    ]
    topic = uuid4()
    with Session(billing_db.engine) as session, session.begin():
        existing_articles = set(session.scalars(select(Article.id)))
        article, anchor = ready(session), ready(session)
        write(session, topic, DEFINITION, sources)
        write(session, topic, member(anchor), sources)
        value = MemberDB(billing_db, sources, article.id, anchor.id, topic)
    yield value
    with Session(billing_db.engine) as session, session.begin():
        session.execute(delete(MemberJudgment))
        session.execute(delete(ContentVector))
        session.execute(delete(TopicMember))
        session.execute(delete(TopicChange))
        session.execute(delete(Topic))
        new_articles = select(Article.id).where(Article.id.not_in(existing_articles))
        session.execute(
            delete(ContentDerivation).where(ContentDerivation.article_id.in_(new_articles))
        )
        session.execute(
            update(Article).where(Article.id.in_(new_articles)).values(current_material_id=None)
        )
        session.execute(delete(ContentMaterial).where(ContentMaterial.article_id.in_(new_articles)))


def test_default_closed_has_no_producer_handler_or_calls(
    member_db: MemberDB, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("UNSPUN_R2_MEMBER_PROCESSING_ENABLED")
    get_settings.cache_clear()
    runtime = build_runtime(member_db.sources, Settings(r1_worker_enabled=True))
    assert not runtime.describe()["member_processing_enabled"]
    assert all(not k.startswith("topic_") for _, k in runtime.handlers)
    with member_db.scope() as session:
        assert (
            enqueue_member_processing(
                session, member_db.article, sources=member_db.sources, now=datetime.now(UTC)
            )
            is None
        )
        assert session.scalar(select(func.count()).select_from(PipelineTask)) == 0
    assert not member_db.calls


@pytest.mark.parametrize(
    "classification,relation",
    [
        ("same_event", "report"),
        ("same_issue", "report"),
        ("background", "background"),
        ("opinion", "opinion"),
        ("explanation", "explanation"),
        ("reprint", "reprint"),
    ],
)
def test_reviewed_chain_and_atomic_idempotent_successors(
    member_db: MemberDB, classification: str, relation: str
) -> None:
    db = member_db
    db.classification = classification
    if classification == "same_issue":
        with db.scope() as session:
            write(session, db.topic, DEFINITION.model_copy(update={"kind": "issue"}), db.sources)
    task = db.enqueue()
    assert db.enqueue() == task
    recall, _ = db.step("topic_recall")
    assert not db.finish(recall, {"candidates": []})
    db.step("topic_judge")
    assert db.judgment().status == "draft"
    review, out = db.step("topic_review")
    assert not db.finish(review, out)
    row = db.judgment()
    assert row.status == "applied" and row.applied_revision
    with db.scope() as session:
        member_row = session.get(TopicMember, (str(db.topic), db.article))
        assert member_row and member_row.relation == relation
        assert qualified_item(
            session, db.article, sources=db.sources, preview=False, as_of=datetime.now(UTC)
        )
        assert session.scalar(select(func.count()).select_from(ContentVector)) == 2
    assert len(db.calls) == 7
    assert [r.stage for r in db.billing.requests()] == [
        "topic_embedding",
        "topic_embedding",
        "topic_judgment",
        *(["topic_review"] * 4),
    ]
    assert all(
        r.task_id and r.task_attempt_id and r.article_id == db.article
        for r in db.billing.requests()
    )


@pytest.mark.parametrize(
    "classification,certainty", [("independent", "certain"), ("same_event", "uncertain")]
)
def test_uncertain_and_independent_never_merge(
    member_db: MemberDB, classification: str, certainty: str
) -> None:
    db = member_db
    db.classification, db.certainty = classification, certainty
    db.enqueue()
    db.step("topic_recall")
    db.step("topic_judge")
    assert db.judgment().status == "independent"
    with db.scope() as session:
        assert session.get(TopicMember, (str(db.topic), db.article)) is None
        assert (
            session.scalar(
                select(func.count())
                .select_from(PipelineTask)
                .where(PipelineTask.kind == "topic_review")
            )
            == 0
        )


def test_empty_candidates_never_call_or_create_topic(member_db: MemberDB) -> None:
    db = member_db
    with db.scope() as session:
        topic = session.get(Topic, str(db.topic))
        assert topic
        topic.status = "archived"
    db.enqueue()
    lease, _ = db.step("topic_recall")
    with db.scope() as session:
        task = session.get(PipelineTask, lease.task_id)
        assert task and task.result == {"judgment_tasks": [], "independent": True}
        assert session.scalar(select(func.count()).select_from(Topic)) == 1
    assert not db.calls


@pytest.mark.parametrize("approved,issues", [(False, []), (True, ["unsupported identity"])])
def test_review_must_be_explicit_and_clean(
    member_db: MemberDB, approved: bool, issues: list[str]
) -> None:
    db = member_db
    db.approved, db.issues = approved, issues
    db.enqueue()
    db.step("topic_recall")
    db.step("topic_judge")
    db.step("topic_review")
    assert db.judgment().status == "rejected"


def test_restart_reuses_checkpoint_vectors_and_journal_reply(member_db: MemberDB) -> None:
    db = member_db
    db.enqueue()
    lease = db.claim("topic_recall")
    first = db.handler().run(lease)
    assert len(db.calls) == 2
    assert db.handler().run(lease) == first
    assert len(db.calls) == 2
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import json, sys
from contextlib import contextmanager
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from unspun.core.config import get_settings
from unspun.core.sources import Source
from unspun.core.tasks import Lease
from unspun.pipeline.member_processing import MemberHandler
value = json.load(sys.stdin)
value['lease']['until'] = datetime.fromisoformat(value['lease']['until'])
engine = create_engine(get_settings().database_url)
@contextmanager
def scope():
    with Session(engine) as session, session.begin():
        yield session
def forbidden(context):
    raise AssertionError('restart must not create a model client')
sources = [Source.model_validate(s) for s in value['sources']]
handler = MemberHandler({s.id: s for s in sources}, scope=scope, client_factory=forbidden)
print(json.dumps(handler.run(Lease(**value['lease']))))
""",
        ],
        input=json.dumps(
            {"lease": asdict(lease), "sources": [s.model_dump(mode="json") for s in db.sources]},
            default=str,
        ),
        env=dict(os.environ),
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    assert json.loads(child.stdout) == first
    assert db.finish(lease, first)
    judge = db.claim("topic_judge")
    out = db.handler().run(judge)
    assert db.handler().run(judge) == out
    assert len(db.calls) == 3
    assert db.finish(judge, out)
    assert len(db.billing.requests()) == 3


def test_expired_claim_rejects_checkpoint_and_late_result(member_db: MemberDB) -> None:
    db = member_db
    db.enqueue()
    lease = db.claim("topic_recall")
    out = db.handler().run(lease)
    with db.scope() as session:
        task = session.get(PipelineTask, lease.task_id)
        assert task
        task.lease_until = datetime.now(UTC) - timedelta(seconds=1)
    with pytest.raises(Blocked, match="lease"):
        db.handler().run(lease)
    assert not db.finish(lease, out)
    with db.scope() as session:
        assert reap_expired(session, datetime.now(UTC)) == 1
        task = session.get(PipelineTask, lease.task_id)
        assert task
        task.due_at = datetime.now(UTC) - timedelta(seconds=1)
    with db.scope() as session:
        task = session.get(PipelineTask, lease.task_id)
        assert task and task.status == "failed" and task.max_attempts == 1
        assert claim(session, queue="paid", kinds={"topic_recall"}, worker="no-retry") is None
    assert len(db.calls) == 2


@pytest.mark.parametrize("change", ["material", "source", "identity", "candidate", "contract"])
def test_input_changes_fence_queued_and_late_results(
    member_db: MemberDB, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    db = member_db
    db.enqueue()
    db.step("topic_recall")
    db.step("topic_judge")
    lease = db.claim("topic_review")
    out = db.handler().run(lease)
    if change == "source":
        source = db.sources[0]
        assert source.r1
        db.sources[0] = source.model_copy(
            update={"r1": source.r1.model_copy(update={"publish_scopes": []})}
        )
    elif change == "contract":
        monkeypatch.setenv("UNSPUN_SUMMARY_MODEL", "synthetic-changed-model")
        get_settings.cache_clear()
    else:
        with db.scope() as session:
            if change == "candidate":
                write(
                    session,
                    db.topic,
                    DEFINITION.model_copy(update={"title": "New revision"}),
                    db.sources,
                )
            else:
                article = session.get(Article, db.article)
                assert article
                if change == "identity":
                    article.url += "?corrected"
                else:
                    material = session.get(ContentMaterial, article.current_material_id)
                    assert material
                    material.extractor_version = "changed-extractor"
    assert db.finish(lease, out)
    assert db.judgment().status == ("rejected" if change == "contract" else "stale")
    with db.scope() as session:
        assert session.get(TopicMember, (str(db.topic), db.article)) is None
    assert len(db.billing.usage()) == 7


def test_vectors_bind_actual_input_and_never_adopt_legacy(member_db: MemberDB) -> None:
    db = member_db
    with db.scope() as session:
        article = session.get(Article, db.article)
        assert article
        article.embedding = [0.0] * EMBEDDING_DIM
        old = vector_input(current_input(session, db.article, db.sources, datetime.now(UTC)))
    db.enqueue()
    db.step("topic_recall")
    assert len(db.calls) == 2
    with db.scope() as session:
        article = session.get(Article, db.article)
        assert article
        article.url += "?new-identity"
        new = vector_input(current_input(session, db.article, db.sources, datetime.now(UTC)))
        assert fingerprint(new) != fingerprint(old)
        assert session.get(ContentVector, fingerprint(new)) is None
    db.enqueue()
    db.step("topic_recall")
    assert len(db.calls) == 3


def test_shared_queue_parallel_claim_and_enqueue_are_idempotent(member_db: MemberDB) -> None:
    db = member_db
    barrier = Barrier(2)

    def enqueue_once() -> int:
        barrier.wait(timeout=5)
        return db.enqueue()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(enqueue_once) for _ in range(2)]
        ids = [future.result(timeout=10) for future in futures]
    assert ids[0] == ids[1]
    handler = db.handler()

    def process() -> bool:
        return process_one(
            "paid", {("paid", "topic_recall"): handler}, worker=uuid4().hex, scope=db.scope
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(process) for _ in range(2)]
        results = [future.result(timeout=15) for future in futures]
    assert results.count(True) == 1 and len(db.calls) == 2


def test_budget_failure_stops_without_auto_resume_and_preserves_draft(member_db: MemberDB) -> None:
    db = member_db
    db.enqueue()
    db.step("topic_recall")
    db.step("topic_judge")
    db.billing.policy(stage_caps={**TOPIC_STAGE_CAPS, "topic_review": "0"})
    handler = db.handler()
    assert process_one(
        "paid", {("paid", "topic_review"): handler}, worker="budget-worker", scope=db.scope
    )
    assert db.judgment().status == "draft" and len(db.calls) == 3
    with db.scope() as session:
        task = session.scalar(select(PipelineTask).where(PipelineTask.kind == "topic_review"))
        assert task and task.status == "blocked" and task.max_attempts == 1
    db.billing.policy(stage_caps=TOPIC_STAGE_CAPS.copy())
    assert not process_one(
        "paid", {("paid", "topic_review"): handler}, worker="budget-worker", scope=db.scope
    )
    assert len(db.billing.usage()) == 3


def test_unknown_full_hold_blocks_retry_after_restart(member_db: MemberDB) -> None:
    db = member_db
    db.enqueue()
    lease = db.claim("topic_recall")
    db.unknown = True
    with pytest.raises(httpx.ReadTimeout):
        db.handler().run(lease)
    held = db.billing.requests()[0]
    assert held.status == "usage_unknown" and held.reserved_usd > 0
    db.unknown = False
    with pytest.raises(Blocked):
        db.handler().run(lease)
    assert db.billing.requests()[0].reserved_usd == held.reserved_usd
    assert len(db.calls) == 1 and not db.billing.usage()


@pytest.mark.parametrize(
    "stage,phase,purpose",
    [
        ("legacy", "embed", "embedding"),
        ("card", "judge", "topic_judgment"),
        ("embedding", "embed", "embedding"),
        ("topic_review", "embed", "grounding"),
    ],
)
def test_topic_task_cannot_borrow_an_old_stage(
    member_db: MemberDB, stage: Any, phase: str, purpose: str
) -> None:
    db = member_db
    db.enqueue()
    lease = db.claim("topic_recall")
    with pytest.raises(LlmError, match="registered task"):
        db.billing.journal.reserve(
            purpose=purpose,
            model=get_settings().summary_model,
            request={"messages": [{"content": "synthetic"}], "max_tokens": 1024},
            context=CallContext(stage=stage, phase=phase, lease=lease),
        )
    assert not db.billing.requests()


def test_new_stages_require_allocation_and_fit_original_production_total(
    member_db: MemberDB,
) -> None:
    db = member_db
    db.enqueue()
    lease = db.claim("topic_recall")
    db.billing.policy(stage_caps=STAGE_CAPS.copy())
    with pytest.raises(Blocked, match="explicit allocation"):
        db.handler().run(lease)
    db.billing.policy(scope="production", stage_caps={**STAGE_CAPS, **TOPIC_STAGE_CAPS})
    with pytest.raises(Blocked, match="original production total"):
        db.handler().run(lease)
    assert not db.calls and not db.billing.requests()


def test_forged_expired_lease_and_review_hash_are_rejected(member_db: MemberDB) -> None:
    db = member_db
    db.enqueue()
    lease = db.claim("topic_recall")
    with pytest.raises(Blocked):
        db.handler().run(replace(lease, input_fingerprint="forged"))
    assert db.finish(lease, db.handler().run(lease))
    db.step("topic_judge")
    review = db.claim("topic_review")
    out = db.handler().run(review)
    out["review"]["audits"][0]["binding"]["decision_fingerprint"] = "0" * 64
    assert db.finish(review, out)
    assert db.judgment().status == "rejected"


def test_bounded_domain_subject_time_candidates_keep_background_and_unknown(
    member_db: MemberDB,
) -> None:
    db = member_db
    with db.scope() as session:
        anchor = session.get(Article, db.anchor)
        assert anchor
        for _ in range(16):
            topic = uuid4()
            write(session, topic, DEFINITION, db.sources)
            write(session, topic, member(anchor, relation="background"), db.sources)
        plan = recall_plan(session, db.article, db.sources, datetime.now(UTC))
        assert len(plan["topics"]) == EMBED_TOPICS
    db.enqueue()
    _, out = db.step("topic_recall")
    assert len(out["candidates"]) == CANDIDATES and len(db.calls) == 2


@pytest.mark.parametrize("vector", [[0.0] * EMBEDDING_DIM, [float("nan")] * EMBEDDING_DIM, [1.0]])
def test_invalid_vectors_are_not_reusable(vector: list[float]) -> None:
    with pytest.raises(ValueError):
        unit_vector(vector, EMBEDDING_DIM)


def test_different_event_and_invalid_evidence_cannot_pass_schema_only(member_db: MemberDB) -> None:
    db = member_db
    db.enqueue()
    _, out = db.step("topic_recall")
    lease = db.claim("topic_judge")
    result = db.handler().run(lease)
    decision = MemberDecision.model_validate(result["decision"])
    with db.scope() as session:
        for modified in (
            decision.model_copy(update={"identity": "same_issue"}),
            decision.model_copy(update={"anchor_facts": ()}),
            decision.model_copy(
                update={
                    "query_facts": (
                        decision.query_facts[0].model_copy(
                            update={
                                "citations": (
                                    decision.query_facts[0]
                                    .citations[0]
                                    .model_copy(update={"quote": "unsupported quotation"}),
                                )
                            }
                        ),
                    )
                }
            ),
        ):
            with pytest.raises(ValueError):
                validate_decision(session, lease.payload, modified)
    assert out["candidates"]


def test_prompt_owns_material_and_supplies_required_output_schema(member_db: MemberDB) -> None:
    db = member_db
    db.enqueue()
    db.step("topic_recall")
    lease = db.claim("topic_judge")
    db.handler().run(lease)
    packet = json.loads(db.calls[-1]["messages"][1]["content"])
    query = packet["query"]
    anchor = packet["candidate"]["topic"]["anchors"][0]["snapshot"]
    assert (query["role"], anchor["role"]) == ("query", "anchor")
    assert query["content"]["article_id"] == db.article
    assert anchor["content"]["article_id"] == db.anchor
    assert query["content"]["paragraphs"][0]["index"] == 0
    assert "qualification" not in query and "identity" not in query
    schema = packet["output_schema"]
    assert set(schema["required"]) == {
        "identity",
        "contribution",
        "certainty",
        "query_facts",
        "anchor_facts",
        "relation",
    }
    ref = schema["$defs"]["MemberCitation"]
    assert set(ref["required"]) == {"reference_id", "quote", "start", "end"}
    assert "voice" not in ref["properties"]


@pytest.mark.parametrize("voice", [None, "query", "anchor"])
def test_missing_or_role_voice_is_not_repaired_or_saved_as_independent(
    member_db: MemberDB, voice: str | None
) -> None:
    from pydantic import ValidationError

    db = member_db
    db.enqueue()
    db.step("topic_recall")
    lease = db.claim("topic_judge")
    raw = db.handler().run(lease)["decision"]
    if voice is None:
        del raw["query_facts"][0]["citations"][0]["reference_id"]
    else:
        raw["query_facts"][0]["citations"][0]["voice"] = voice
    with pytest.raises(ValidationError):
        MemberDecision.model_validate(raw)
    with db.scope() as session:
        assert session.scalar(select(MemberJudgment)) is None
        assert session.get(Topic, str(db.topic)).revision == 2  # type: ignore[union-attr]


def test_citations_cannot_borrow_another_owner_or_invisible_suffix(member_db: MemberDB) -> None:
    from copy import deepcopy

    db = member_db
    db.enqueue()
    db.step("topic_recall")
    lease = db.claim("topic_judge")
    decision = MemberDecision.model_validate(db.handler().run(lease)["decision"])
    packet = deepcopy(lease.payload)
    own = packet["query"]["content"]
    original_quote = decision.query_facts[0].citations[0].quote
    own["paragraphs"] = [{"kind": "paragraph", "text": "x" * 12000 + original_quote}]
    with db.scope() as session:
        with pytest.raises(ValueError, match="stale member reference"):
            validate_decision(session, packet, decision)
        wrong_owner = decision.query_facts[0].model_copy(
            update={"citations": decision.anchor_facts[0].citations}
        )
        for identity in ("same_occurrence", "none"):
            invalid = decision.model_copy(
                update={"identity": identity, "query_facts": (wrong_owner,)}
            )
            with pytest.raises(ValueError, match="another role"):
                validate_decision(session, lease.payload, invalid)


def test_registered_allocation_fits_existing_total_without_changing_policy(
    member_db: MemberDB,
) -> None:
    from unspun.core.billing_models import BudgetPolicy

    db = member_db
    allocation = {"legacy": "0", "card": "9.50", "guide": "2", "embedding": "1", **TOPIC_STAGE_CAPS}
    assert sum(Decimal(v) for v in allocation.values()) == Decimal("13.50")
    db.billing.policy(scope="production", monthly_limit_usd=Decimal("13.50"), stage_caps=allocation)
    db.enqueue()
    db.step("topic_recall")
    db.step("topic_judge")
    db.step("topic_review")
    assert db.judgment().status == "applied"
    with db.scope() as session:
        policy = session.get(BudgetPolicy, 1)
        assert (
            policy
            and policy.stage_caps == allocation
            and policy.monthly_limit_usd == Decimal("13.50")
        )


def test_two_reviewers_cas_one_topic_without_overwriting_new_revision(member_db: MemberDB) -> None:
    db = member_db
    db.enqueue()
    db.step("topic_recall")
    db.step("topic_judge")
    first = db.claim("topic_review")
    first_result = db.handler().run(first)
    with db.scope() as session:
        other = ready(session)
        second_article = other.id
        enqueue_member_processing(session, other.id, sources=db.sources, now=datetime.now(UTC))
    db.step("topic_recall")
    db.step("topic_judge")
    second = db.claim("topic_review")
    second_result = db.handler().run(second)
    barrier = Barrier(2)

    def finish(lease: Lease, result: dict[str, Any]) -> bool:
        barrier.wait(timeout=5)
        return db.finish(lease, result)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(finish, first, first_result),
            pool.submit(finish, second, second_result),
        ]
        assert all(f.result(timeout=15) for f in futures)
    with db.scope() as session:
        rows = list(session.scalars(select(MemberJudgment)))
        assert sorted(r.status for r in rows) == ["applied", "stale"]
        assert (
            session.scalar(
                select(func.count())
                .select_from(TopicMember)
                .where(TopicMember.article_id.in_([db.article, second_article]))
            )
            == 1
        )
    assert len(db.billing.usage()) == 13


def test_multiple_topics_keep_independent_cas_and_removals_are_not_readded(
    member_db: MemberDB,
) -> None:
    from unspun.core.topic_contracts import RemoveMember

    db = member_db
    with db.scope() as session:
        anchor = session.get(Article, db.anchor)
        assert anchor
        other = uuid4()
        write(session, other, DEFINITION.model_copy(update={"kind": "issue"}), db.sources)
        write(session, other, member(anchor), db.sources)
    db.classification = "explanation"
    db.enqueue()
    db.step("topic_recall")
    for _ in range(2):
        db.step("topic_judge")
    for _ in range(2):
        db.step("topic_review")
    with db.scope() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(TopicMember)
                .where(TopicMember.article_id == db.article)
            )
            == 2
        )
        write(session, db.topic, RemoveMember(article_id=db.article), db.sources)
        plan = recall_plan(session, db.article, db.sources, datetime.now(UTC))
        assert not plan["topics"]


def test_old_background_and_unknown_original_time_remain_recallable(member_db: MemberDB) -> None:
    from unspun.core.content_reading import ContentInput, publication_at

    db = member_db
    with db.scope() as session:
        old, unknown = ready(session, age=150), ready(session, kind="modified")
        for article in (old, unknown):
            topic = uuid4()
            write(session, topic, DEFINITION, db.sources)
            write(session, topic, member(article, relation="background"), db.sources)
        plan = recall_plan(session, db.article, db.sources, datetime.now(UTC))
        assert len(plan["topics"]) == 3
        times = [
            publication_at(
                ContentInput.model_validate(t["anchors"][0]["snapshot"]["content"]).metadata
            )
            for t in plan["topics"]
        ]
        assert times[-1] is None
        assert times[0] and times[1] and times[0] > times[1]
