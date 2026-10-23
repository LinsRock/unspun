"""Mock-only R2-07 integration: real queue, transactions and isolated fee journal."""

import copy
import json
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from tests.test_billing import BillingDB
from tests.test_content_feed import ready
from tests.test_topics import DEFINITION, member, write
from unspun.core.billing import CallContext
from unspun.core.config import Settings, get_settings
from unspun.core.content_publication import qualified_item
from unspun.core.llm import LlmClient, LlmError
from unspun.core.models import Article, ContentDerivation, ContentMaterial
from unspun.core.sources import Source, load_sources
from unspun.core.synthesis_contracts import (
    CHECKS,
    MANUAL_VERSION,
    ManualReview,
    SynthesisDraft,
    text_contract,
)
from unspun.core.synthesis_models import TopicSynthesis
from unspun.core.task_models import PipelineTask
from unspun.core.tasks import Lease, claim, complete, reap_expired
from unspun.core.topic_contracts import RemoveMember
from unspun.core.topic_models import Topic, TopicChange, TopicDerivation, TopicMember, TopicUpdate
from unspun.core.topic_synthesis import qualified_topic_text, validate_draft
from unspun.core.topics import validate_version
from unspun.pipeline.r1_runtime import build_runtime
from unspun.pipeline.r1_worker import Blocked, Handlers, process_one
from unspun.pipeline.topic_synthesis import SynthesisHandler, enqueue_synthesis

pytest_plugins = ["tests.test_billing"]
REVIEWER = ManualReview(
    actor="synthetic-manual-reviewer",
    identity="agent_manual",
    basis="Mock protocol fixture; not human or model quality",
)
ZH = "\u6d4b\u8bd5\u6750\u6599\u62a5\u9053\u7684\u65b0\u8fdb\u5c55"


def mock_draft(packet: dict[str, Any]) -> dict[str, Any]:
    contributions: list[dict[str, Any]] = []
    for index, row in enumerate(packet["members"]):
        content = row["content"]
        claim = {
            "text": ZH + str(index),
            "attribution": "Synthetic source",
            "limitations": ["Mock evidence; observed material only"],
            "evidence": [
                {
                    "article_id": content["article_id"],
                    "material_id": content["material_id"],
                    "paragraph": 0,
                    "quote": content["paragraphs"][0]["text"][:100],
                    "voice": "reported",
                }
            ],
        }
        contributions.append(
            {
                **claim,
                "classification": "development" if index == 0 else "background",
                "progress_key": "synthetic-progress" if index == 0 else None,
                "change": "new" if index == 0 else "none",
                "novelty_basis": "Synthetic novelty control",
                "occurred": {"precision": "unknown"},
                "reported": {"precision": "unknown"},
            }
        )
    claim = {k: contributions[0][k] for k in ("text", "attribution", "limitations", "evidence")}
    return {
        "outcome": "ready",
        "reason": "Explicit mock response",
        "contributions": contributions,
        "overview": [claim],
        "guide": [claim],
    }


@dataclass
class SynthesisDB:
    billing: BillingDB
    sources: list[Source]
    topic: UUID
    article: int
    other: int
    calls: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    draft_override: dict[str, Any] | None = None
    reject: str | None = None
    missing: bool = False
    unknown: bool = False
    truncate: bool = False
    mark_mock: bool = True

    @contextmanager
    def scope(self) -> Generator[Session]:
        with Session(self.billing.engine) as session, session.begin():
            yield session

    def transport(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.calls.append(body)
        if self.unknown:
            raise httpx.ReadTimeout("explicit mock timeout")
        packet = json.loads(body["messages"][1]["content"])
        if "draft" in packet:
            raw = {
                "checks": [
                    {
                        "target": t,
                        "dimension": d,
                        "supported": d != self.reject,
                        "reason": "Explicit mock semantic verdict; no quality credit",
                    }
                    for t in packet["targets"]
                    for d in packet["dimensions"]
                ],
                "issues": [],
            }
            if self.missing:
                raw["checks"].pop()
        else:
            raw = self.draft_override or mock_draft(packet)
        return httpx.Response(
            200,
            json={
                "id": "mock-" + uuid4().hex,
                "unspun_mock": self.mark_mock,
                "choices": [
                    {
                        "finish_reason": "length" if self.truncate else "stop",
                        "message": {"content": json.dumps(raw)},
                    }
                ],
                "usage": {"cost": 0, "prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    def handler(self) -> SynthesisHandler:
        return SynthesisHandler(
            {s.id: s for s in self.sources},
            scope=self.scope,
            allow_mock=True,
            client_factory=lambda context: LlmClient(
                context=context, transport=httpx.MockTransport(self.transport)
            ),
        )

    def enqueue(self, revision: int | None = None) -> int:
        with self.scope() as session:
            topic = session.get(Topic, str(self.topic))
            assert topic
            task = enqueue_synthesis(
                session,
                self.topic,
                revision or topic.revision,
                REVIEWER,
                sources=self.sources,
                now=datetime.now(UTC),
                response_mode="mock",
            )
            assert task
            return task

    def claim(self, kind: str) -> Lease:
        with self.scope() as session:
            lease = claim(
                session, queue="paid", kinds={kind}, worker="mock-worker", lease_seconds=900
            )
            assert lease
            return lease

    def finish(self, lease: Lease, result: dict[str, Any]) -> bool:
        with self.scope() as session:
            return complete(
                session, lease, apply=lambda db: self.handler().apply(db, lease, result)
            )

    def step(self, kind: str) -> tuple[Lease, dict[str, Any]]:
        lease = self.claim(kind)
        result = self.handler().run(lease)
        assert self.finish(lease, result)
        return lease, result

    def row(self) -> TopicSynthesis:
        with self.scope() as session:
            row = session.scalar(select(TopicSynthesis).order_by(TopicSynthesis.created_at.desc()))
            assert row
            session.expunge(row)
            return row


@pytest.fixture
def synthesis_db(billing_db: BillingDB, monkeypatch: pytest.MonkeyPatch) -> Generator[SynthesisDB]:
    monkeypatch.setenv("UNSPUN_R2_SYNTHESIS_ENABLED", "true")
    get_settings.cache_clear()
    billing_db.policy(stage_caps={"topic_synthesis": "0.45", "topic_synthesis_review": "0.45"})
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
        original = set(session.scalars(select(Article.id)))
        article, other = ready(session), ready(session)
        write(session, topic, DEFINITION, sources)
        for a in (article, other):
            write(session, topic, member(a, decision_version=MANUAL_VERSION), sources)
        fixture = SynthesisDB(billing_db, sources, topic, article.id, other.id)
    yield fixture
    with Session(billing_db.engine) as session, session.begin():
        session.execute(delete(TopicSynthesis))
        session.execute(delete(TopicDerivation))
        session.execute(delete(TopicUpdate))
        session.execute(delete(TopicMember))
        session.execute(delete(TopicChange))
        session.execute(delete(Topic))
        ids = select(Article.id).where(Article.id.not_in(original))
        session.execute(delete(ContentDerivation).where(ContentDerivation.article_id.in_(ids)))
        session.execute(update(Article).where(Article.id.in_(ids)).values(current_material_id=None))
        session.execute(delete(ContentMaterial).where(ContentMaterial.article_id.in_(ids)))


def test_default_closed_and_no_automatic_producer(
    synthesis_db: SynthesisDB, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("UNSPUN_R2_SYNTHESIS_ENABLED")
    get_settings.cache_clear()
    db = synthesis_db
    runtime = build_runtime(db.sources, Settings(r1_worker_enabled=True))
    assert not runtime.describe()["synthesis_enabled"]
    assert not Settings().r2_topic_publication_enabled
    with db.scope() as session:
        assert (
            enqueue_synthesis(
                session, db.topic, 3, REVIEWER, sources=db.sources, now=datetime.now(UTC)
            )
            is None
        )
        assert session.scalar(select(func.count()).select_from(PipelineTask)) == 0
    assert not db.calls


def test_automatic_member_is_not_a_manual_input(synthesis_db: SynthesisDB) -> None:
    db = synthesis_db
    with db.scope() as session:
        article = session.get(Article, db.article)
        assert article
        write(session, db.topic, member(article, decision_version="r2-member-v6"), db.sources)
    with pytest.raises(ValueError, match="manual"):
        db.enqueue()
    assert not db.calls


def test_atomic_chain_dedupe_mock_label_and_independent_reading(
    synthesis_db: SynthesisDB, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = synthesis_db
    task = db.enqueue(3)
    assert db.enqueue(3) == task
    generation, _ = db.step("topic_synthesize")
    assert db.row().status == "draft"
    review, result = db.step("topic_synthesis_review")
    assert not db.finish(review, result)
    assert db.enqueue(3) == task
    row = db.row()
    assert row.status == "applied" and row.response_mode == "mock"
    assert len(db.calls) == 2 and all(
        c.stage.startswith("topic_synthesis") for c in db.billing.requests()
    )
    assert row.generation_receipt["original_attempt_id"] == generation.attempt_id
    assert row.applied and len(row.applied["updates"]) == 1
    monkeypatch.setenv("UNSPUN_R2_TOPIC_PUBLICATION_ENABLED", "true")
    get_settings.cache_clear()
    with db.scope() as session:
        assert (
            qualified_topic_text(session, db.topic, sources=db.sources, now=datetime.now(UTC))
            is None
        )
        assert session.scalar(select(func.count()).select_from(TopicUpdate)) == 1
        assert session.scalar(select(func.count()).select_from(TopicDerivation)) == 2
        assert qualified_item(
            session, db.article, preview=False, as_of=datetime.now(UTC), sources=db.sources
        )


@pytest.mark.parametrize("dimension", CHECKS)
def test_quote_matches_do_not_replace_semantic_checks(
    synthesis_db: SynthesisDB, dimension: str
) -> None:
    db = synthesis_db
    db.enqueue()
    db.step("topic_synthesize")
    db.reject = dimension
    db.step("topic_synthesis_review")
    assert db.row().status == "rejected"
    with db.scope() as session:
        assert session.scalar(select(func.count()).select_from(TopicUpdate)) == 0
        assert qualified_item(
            session, db.article, preview=False, as_of=datetime.now(UTC), sources=db.sources
        )


def test_missing_review_check_and_forged_response_rejected(synthesis_db: SynthesisDB) -> None:
    db = synthesis_db
    db.enqueue()
    db.step("topic_synthesize")
    db.missing = True
    lease = db.claim("topic_synthesis_review")
    result = db.handler().run(lease)
    forged = copy.deepcopy(result)
    forged["raw"]["issues"] = ["forged content"]
    with pytest.raises(LlmError, match="differs"):
        db.finish(lease, forged)
    assert db.finish(lease, result) and db.row().status == "rejected"


@pytest.mark.parametrize("classification", ["duplicate", "background", "opinion", "insufficient"])
def test_no_progress_abstains_without_refresh_or_review(
    synthesis_db: SynthesisDB, classification: str
) -> None:
    db = synthesis_db
    db.enqueue()
    lease = db.claim("topic_synthesize")
    from unspun.core.topic_synthesis import prompt_packet

    draft = mock_draft(prompt_packet(lease.payload))
    draft.update(outcome="abstained", overview=[], guide=[])
    for c in draft["contributions"]:
        c.update(classification=classification, change="none", progress_key=None)
    db.draft_override = draft
    assert db.finish(lease, db.handler().run(lease))
    assert db.row().status == "abstained" and len(db.calls) == 1
    with db.scope() as session:
        assert session.scalar(select(func.count()).select_from(TopicUpdate)) == 0
        assert session.scalar(select(func.count()).select_from(PipelineTask)) == 1


@pytest.mark.parametrize("change", ["remove", "correct", "material", "source"])
def test_dependency_changes_reject_late_review_keep_history(
    synthesis_db: SynthesisDB, change: str
) -> None:
    db = synthesis_db
    db.enqueue()
    db.step("topic_synthesize")
    lease = db.claim("topic_synthesis_review")
    result = db.handler().run(lease)
    with db.scope() as session:
        article = session.get(Article, db.article)
        assert article
        if change == "remove":
            write(session, db.topic, RemoveMember(article_id=db.article), db.sources)
        elif change == "correct":
            write(
                session,
                db.topic,
                member(article, relation="opinion", decision_version=MANUAL_VERSION),
                db.sources,
            )
        elif change == "material":
            article.current_material_id = None
        else:
            source = db.sources[0]
            assert source.r1
            db.sources = [
                source.model_copy(update={"r1": source.r1.model_copy(update={"publish": False})})
            ]
    if change == "source":
        with pytest.raises(Blocked):
            db.finish(lease, result)
    else:
        assert db.finish(lease, result) and db.row().status == "stale"
    with db.scope() as session:
        assert session.scalar(select(func.count()).select_from(TopicUpdate)) == 0
        assert session.get(TopicSynthesis, db.row().input_fingerprint)


def test_source_close_and_member_correction_invalidate_applied_drafts(
    synthesis_db: SynthesisDB,
) -> None:
    db = synthesis_db
    db.enqueue()
    db.step("topic_synthesize")
    db.step("topic_synthesis_review")
    with db.scope() as session:
        rows = list(session.scalars(select(TopicDerivation)))
        assert all(
            validate_version(
                session, r, sources=db.sources, now=datetime.now(UTC), contract=text_contract()
            ).valid
            for r in rows
        )
        source = db.sources[0]
        assert source.r1
        closed = [source.model_copy(update={"r1": source.r1.model_copy(update={"publish": False})})]
        assert all(
            not validate_version(
                session, r, sources=closed, now=datetime.now(UTC), contract=text_contract()
            ).valid
            for r in rows
        )
        write(session, db.topic, RemoveMember(article_id=db.article), db.sources)
        assert all(
            not validate_version(
                session, r, sources=db.sources, now=datetime.now(UTC), contract=text_contract()
            ).valid
            for r in rows
        )
        assert qualified_item(
            session, db.article, preview=False, as_of=datetime.now(UTC), sources=db.sources
        )


def test_budget_deferral_and_resume_require_own_allocation(synthesis_db: SynthesisDB) -> None:
    db = synthesis_db
    task_id = db.enqueue()
    db.billing.policy(stage_caps={"card": "10", "guide": "2"})
    handler = db.handler()
    handlers: Handlers = {("paid", "topic_synthesize"): handler}
    assert process_one("paid", handlers, worker="mock", scope=db.scope)
    with db.scope() as session:
        task = session.get(PipelineTask, task_id)
        assert task and task.status == "budget_deferred" and task.failures == 0
        task.due_at = datetime.now(UTC) - timedelta(seconds=1)
    assert not db.calls and not db.billing.requests()
    db.billing.policy(stage_caps={"topic_synthesis": "0.45", "topic_synthesis_review": "0.45"})
    assert process_one("paid", handlers, worker="mock", scope=db.scope)
    assert db.row().status == "draft" and len(db.calls) == 1


def test_late_response_reclaim_reuses_physical_receipt(synthesis_db: SynthesisDB) -> None:
    db = synthesis_db
    db.enqueue()
    lease = db.claim("topic_synthesize")
    result = db.handler().run(lease)
    with db.scope() as session:
        task = session.get(PipelineTask, lease.task_id)
        assert task
        task.lease_until = datetime.now(UTC) - timedelta(seconds=2)
        session.flush()
        assert reap_expired(session, datetime.now(UTC), task_ids=frozenset({task.id})) == 1
        task.due_at = datetime.now(UTC) - timedelta(seconds=1)
    assert not db.finish(lease, result)
    recovered, _ = db.step("topic_synthesize")
    assert recovered.version > lease.version
    assert len(db.calls) == 1
    assert db.row().generation_receipt["original_attempt_id"] == lease.attempt_id


def test_transaction_failure_recovers_without_duplicate_progress_or_call(
    synthesis_db: SynthesisDB,
) -> None:
    db = synthesis_db
    db.enqueue()
    db.step("topic_synthesize")
    lease = db.claim("topic_synthesis_review")
    result = db.handler().run(lease)
    with pytest.raises(RuntimeError), db.scope() as session:
        assert complete(session, lease, apply=lambda s: db.handler().apply(s, lease, result))
        raise RuntimeError("mock crash before commit")
    assert db.row().status == "draft"
    assert db.finish(lease, db.handler().run(lease))
    assert db.row().status == "applied" and len(db.calls) == 2


def test_unknown_preserves_full_hold_and_blocks_recovery(synthesis_db: SynthesisDB) -> None:
    db = synthesis_db
    db.enqueue()
    db.unknown = True
    handler = db.handler()
    assert process_one(
        "paid", {("paid", "topic_synthesize"): handler}, worker="mock", scope=db.scope
    )
    first = db.billing.requests()[0]
    assert first.status == "usage_unknown" and first.reserved_usd > 0
    with db.scope() as session:
        task = session.get(PipelineTask, first.task_id)
        assert task
        task.due_at = datetime.now(UTC) - timedelta(seconds=1)
    assert process_one(
        "paid", {("paid", "topic_synthesize"): handler}, worker="mock", scope=db.scope
    )
    assert len(db.calls) == 1
    current = db.billing.requests()[0]
    assert current.reserved_usd == first.reserved_usd and current.status == "usage_unknown"


@pytest.mark.parametrize("bad", ["stage", "kind", "model", "phase"])
def test_billing_rejects_stage_borrowing(synthesis_db: SynthesisDB, bad: str) -> None:
    db = synthesis_db
    db.enqueue()
    lease = db.claim("topic_synthesize")
    context = CallContext(
        stage="topic_synthesis", phase="synthesize", logical_key="mock", lease=lease
    )
    model = get_settings().summary_model
    if bad == "stage":
        context = replace(context, stage="card")
    elif bad == "kind":
        context = replace(context, lease=replace(lease, kind="process_card"))
    elif bad == "model":
        model = get_settings().viewpoint_model
    else:
        context = replace(context, phase="generate")
    with pytest.raises(LlmError):
        db.billing.journal.reserve(
            purpose="topic_synthesis", model=model, request={"max_tokens": 4096}, context=context
        )
    assert not db.billing.requests()


def test_reprints_and_temporal_refresh_are_not_progress(synthesis_db: SynthesisDB) -> None:
    db = synthesis_db
    with db.scope() as session:
        article = session.get(Article, db.article)
        assert article
        write(
            session,
            db.topic,
            member(article, relation="reprint", decision_version=MANUAL_VERSION),
            db.sources,
        )
    db.enqueue()
    lease = db.claim("topic_synthesize")
    from unspun.core.topic_synthesis import prompt_packet

    draft = SynthesisDraft.model_validate(mock_draft(prompt_packet(lease.payload)))
    with db.scope() as session, pytest.raises(ValueError, match="reprints"):
        validate_draft(session, lease.payload, draft)


@pytest.mark.parametrize("bad", ["unmarked", "truncated"])
def test_mock_marking_and_bounded_output_no_paid_retry(synthesis_db: SynthesisDB, bad: str) -> None:
    db = synthesis_db
    db.enqueue()
    lease = db.claim("topic_synthesize")
    db.mark_mock, db.truncate = bad != "unmarked", bad == "truncated"
    with pytest.raises(LlmError):
        db.handler().run(lease)
    assert len(db.calls) == len(db.billing.requests()) == 1


@pytest.mark.parametrize("issue", [False, True])
def test_new_discussion_focus_requires_issue_and_review(
    synthesis_db: SynthesisDB, issue: bool
) -> None:
    db = synthesis_db
    if issue:
        with db.scope() as session:
            write(session, db.topic, DEFINITION.model_copy(update={"kind": "issue"}), db.sources)
    db.enqueue()
    lease = db.claim("topic_synthesize")
    from unspun.core.topic_synthesis import prompt_packet

    draft = mock_draft(prompt_packet(lease.payload))
    draft["contributions"][0]["classification"] = "discussion_focus"
    db.draft_override = draft
    result = db.handler().run(lease)
    if not issue:
        with pytest.raises(ValueError, match="issue"):
            db.finish(lease, result)
        return
    assert db.finish(lease, result)
    db.step("topic_synthesis_review")
    with db.scope() as session:
        progress = session.scalar(select(TopicUpdate))
        assert progress and progress.payload["classification"] == "discussion_focus"
        assert progress.payload["attribution"] and progress.payload["limitations"]


@pytest.mark.parametrize("correction", ["text", "attribution", "limitations"])
def test_correction_is_append_only_and_cannot_refresh_report_time(
    synthesis_db: SynthesisDB,
    correction: str,
) -> None:
    db = synthesis_db
    db.enqueue()
    db.step("topic_synthesize")
    db.step("topic_synthesis_review")
    prior = db.row()
    db.enqueue()
    lease = db.claim("topic_synthesize")
    draft = copy.deepcopy(prior.draft)
    first = draft["contributions"][0]
    first.update(change="correction", novelty_basis="Mock supported assertion correction")
    first[correction] = (
        ["Corrected material qualification"] if correction == "limitations" else ZH + "1"
    )
    first["reported"] = {
        "precision": "date",
        "on": "2026-10-23",
        "basis": first["evidence"][0]["quote"][:8],
    }
    with db.scope() as session, pytest.raises(ValueError, match="cannot refresh"):
        validate_draft(session, lease.payload, SynthesisDraft.model_validate(draft))
    first["reported"] = {"precision": "unknown"}
    db.draft_override = draft
    assert db.finish(lease, db.handler().run(lease))
    db.step("topic_synthesis_review")
    with db.scope() as session:
        updates = list(session.scalars(select(TopicUpdate).order_by(TopicUpdate.revision)))
        assert len(updates) == 2 and updates[1].supersedes_revision == updates[0].revision
        assert updates[0].update_id == updates[1].update_id
        assert updates[0].payload["reported"] == updates[1].payload["reported"]
        assert not validate_version(
            session, updates[0], sources=db.sources, now=datetime.now(UTC)
        ).valid
        assert validate_version(
            session, updates[1], sources=db.sources, now=datetime.now(UTC)
        ).valid


def test_added_duplicate_member_and_processing_time_do_not_refresh_progress(
    synthesis_db: SynthesisDB,
) -> None:
    db = synthesis_db
    db.enqueue()
    db.step("topic_synthesize")
    db.step("topic_synthesis_review")
    with db.scope() as session:
        before = session.scalar(select(TopicUpdate))
        assert before
        saved = (before.revision, before.payload, before.recorded_at)
        new = ready(session)
        write(
            session,
            db.topic,
            member(new, relation="reprint", decision_version=MANUAL_VERSION),
            db.sources,
        )
    db.enqueue()
    lease = db.claim("topic_synthesize")
    from unspun.core.topic_synthesis import prompt_packet

    draft = mock_draft(prompt_packet(lease.payload))
    draft.update(outcome="abstained", overview=[], guide=[])
    for c in draft["contributions"]:
        c.update(classification="duplicate", change="none", progress_key="synthetic-progress")
    db.draft_override = draft
    assert db.finish(lease, db.handler().run(lease))
    with db.scope() as session:
        rows = list(session.scalars(select(TopicUpdate)))
        assert len(rows) == 1
        assert (rows[0].revision, rows[0].payload, rows[0].recorded_at) == saved
        assert validate_version(session, rows[0], sources=db.sources, now=datetime.now(UTC)).valid


@pytest.mark.parametrize(
    "bad", ["owner", "paragraph", "quote", "chinese", "limit", "time", "coverage"]
)
def test_structural_limits_do_not_invent_or_expand_material(
    synthesis_db: SynthesisDB, bad: str
) -> None:
    db = synthesis_db
    db.enqueue()
    lease = db.claim("topic_synthesize")
    from unspun.core.topic_synthesis import prompt_packet

    draft = mock_draft(prompt_packet(lease.payload))
    ref = draft["contributions"][0]["evidence"][0]
    if bad == "owner":
        ref["article_id"] = 9999999
    elif bad == "paragraph":
        ref["paragraph"] = 99
    elif bad == "quote":
        ref["quote"] = "absent fabricated quotation"
    elif bad == "chinese":
        draft["overview"][0]["text"] = "English only"
    elif bad == "limit":
        draft["guide"][0]["limitations"] = []
    elif bad == "time":
        draft["contributions"][0]["occurred"] = {
            "precision": "date",
            "on": "2026-10-23",
            "basis": "absent date",
        }
    else:
        draft["contributions"].pop()
    with db.scope() as session, pytest.raises(ValueError):
        validate_draft(session, lease.payload, SynthesisDraft.model_validate(draft))


def test_expired_input_blocks_before_mock_network(synthesis_db: SynthesisDB) -> None:
    db = synthesis_db
    db.enqueue()
    with db.scope() as session:
        write(session, db.topic, RemoveMember(article_id=db.other), db.sources)
    lease = db.claim("topic_synthesize")
    with pytest.raises(Blocked):
        db.handler().run(lease)
    assert not db.calls and not db.billing.requests()


def test_receipt_from_another_request_cannot_approve(synthesis_db: SynthesisDB) -> None:
    db = synthesis_db
    db.enqueue()
    _, generation = db.step("topic_synthesize")
    lease = db.claim("topic_synthesis_review")
    result = db.handler().run(lease)
    result["receipt"] = generation["receipt"]
    with pytest.raises(LlmError, match="physical request"):
        db.finish(lease, result)
    assert db.row().status == "draft"


def test_changed_generation_receipt_blocks_successor(synthesis_db: SynthesisDB) -> None:
    db = synthesis_db
    db.enqueue()
    db.step("topic_synthesize")
    row = db.row()
    with db.scope() as session:
        stored = session.get(TopicSynthesis, row.input_fingerprint)
        assert stored
        stored.generation_receipt = {**stored.generation_receipt, "response_fingerprint": "0" * 64}
    lease = db.claim("topic_synthesis_review")
    with pytest.raises(Blocked, match="binding"):
        db.handler().run(lease)
    assert len(db.calls) == 1


def test_corrected_manual_input_has_a_fresh_recovery_request(synthesis_db: SynthesisDB) -> None:
    db = synthesis_db
    old_id = db.enqueue()
    lease = db.claim("topic_synthesize")
    result = db.handler().run(lease)
    with db.scope() as session:
        article = session.get(Article, db.article)
        assert article
        write(
            session,
            db.topic,
            member(
                article, basis="Corrected manual membership reason", decision_version=MANUAL_VERSION
            ),
            db.sources,
        )
    assert db.finish(lease, result) and db.row().status == "stale"
    assert db.enqueue() != old_id
    db.step("topic_synthesize")
    db.step("topic_synthesis_review")
    assert db.row().status == "applied"
    with db.scope() as session:
        assert session.scalar(select(func.count()).select_from(TopicSynthesis)) == 2


@pytest.mark.parametrize("value", ["true", 1, None])
def test_semantic_verdict_requires_a_json_boolean(value: Any) -> None:
    from unspun.core.synthesis_contracts import SemanticCheck

    with pytest.raises(ValueError):
        SemanticCheck.model_validate(
            {
                "target": "overview:0",
                "dimension": "support",
                "supported": value,
                "reason": "Malformed mock verdict",
            }
        )


@pytest.mark.parametrize(
    "field_name,value",
    [
        ("source_id", "another-source"),
        ("article_id", 999999),
        ("queue", "guide"),
        ("strategy_version", "legacy"),
    ],
)
def test_forged_lease_fields_cannot_use_the_synthesis_handler(
    synthesis_db: SynthesisDB, field_name: str, value: Any
) -> None:
    db = synthesis_db
    db.enqueue()
    lease = db.claim("topic_synthesize")
    with pytest.raises(Blocked):
        db.handler().run(replace(lease, **{field_name: value}))
    assert not db.calls


def test_mock_progress_cannot_become_a_live_input(synthesis_db: SynthesisDB) -> None:
    db = synthesis_db
    db.enqueue()
    db.step("topic_synthesize")
    db.step("topic_synthesis_review")
    with db.scope() as session:
        topic = session.get(Topic, str(db.topic))
        assert topic
        with pytest.raises(ValueError, match="mock progress"):
            enqueue_synthesis(
                session,
                db.topic,
                topic.revision,
                REVIEWER,
                sources=db.sources,
                now=datetime.now(UTC),
                response_mode="live",
            )
    assert len(db.calls) == 2


def test_unchanged_assertion_cannot_refresh_under_a_new_key(synthesis_db: SynthesisDB) -> None:
    db = synthesis_db
    db.enqueue()
    db.step("topic_synthesize")
    db.step("topic_synthesis_review")
    draft = copy.deepcopy(db.row().draft)
    db.enqueue()
    lease = db.claim("topic_synthesize")
    draft["contributions"][0]["progress_key"] = "new-source-same-assertion"
    with db.scope() as session, pytest.raises(ValueError, match="new key"):
        validate_draft(session, lease.payload, SynthesisDraft.model_validate(draft))
    draft["contributions"][0].update(progress_key="synthetic-progress", change="correction")
    with db.scope() as session, pytest.raises(ValueError, match="duplicate assertion"):
        validate_draft(session, lease.payload, SynthesisDraft.model_validate(draft))
