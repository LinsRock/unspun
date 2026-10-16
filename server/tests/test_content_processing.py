"""Grounding gates, version recovery, and immutable R1 derivation persistence."""

import copy
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from unspun.core.content import ContentMetadata, ContentTime, Paragraph, fingerprint
from unspun.core.content_reading import ContentInput, cheap_exclusion
from unspun.core.models import Article, ContentDerivation, ContentMaterial
from unspun.core.tasks import claim
from unspun.pipeline.content_processing import (
    apply_processing,
    enqueue_processing,
    organize,
    processing_fingerprint,
    request_context,
)

NOW = datetime(2026, 10, 16, 9, tzinfo=UTC)
TEXT = (
    "\u7814\u7a76\u8005\u5c55\u793a\u4e86\u4e09\u4e2a\u6d4b\u91cf"
    "\u7ed3\u679c\uff0c\u4f46\u8fd9\u4e9b\u7ed3\u679c\u5c1a\u672a"
    "\u7ecf\u8fc7\u72ec\u7acb\u9a8c\u8bc1\u3002"
)
TITLE = "\u7814\u7a76\u5c55\u793a\u6d4b\u91cf\u7ed3\u679c"


def approval(supported: bool = True) -> dict[str, Any]:
    return {
        "title_supported": True,
        "classification_supported": True,
        "claim_checks": [{"index": 0, "supported": supported, "reason": ""}],
        "issues": [],
    }


class FakeClient:
    def __init__(self, out: dict[str, Any]) -> None:
        self.out, self.calls = out, 0

    def chat_json(self, session: Session, **kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        assert not session.in_transaction(), (
            "no task/candidate transaction held during a model call"
        )
        return copy.deepcopy(self.out)

    def embed(self, session: Session, texts: list[str]) -> list[list[float]]:
        pytest.fail("R1 has no embedding consumer")


def input_content(**values: Any) -> ContentInput:
    return ContentInput(
        article_id=values.pop("article_id", 1),
        material_id=values.pop("material_id", 1),
        source_id="synthetic-r1",
        title=TITLE,
        metadata=values.pop("metadata", ContentMetadata(form="article")),
        scope=values.pop("scope", "open_text_unit"),
        paragraphs=values.pop("paragraphs", (Paragraph(text=TEXT),)),
        material_fingerprint="body-v1",
        metadata_fingerprint="metadata-v1",
        extractor_version="synthetic-v1",
        material_observed_at=NOW,
        **values,
    )


def draft(**values: Any) -> dict[str, Any]:
    claim = {"text": TEXT, "quote": TEXT, "voice": "reported"}
    return {
        "title_zh": TITLE,
        "genre": "knowledge",
        "domains": ["science"],
        "topics": ["\u7814\u7a76"],
        "claims": [claim],
        "reading_value": 1,
        "reading_reason": claim,
        "include": True,
        "reason": "supported_material",
        **values,
    }


@pytest.mark.parametrize("kind", ["none", "title_only", "duplicate", "old_brief", "old_report"])
def test_cheap_filters_make_no_model_call(kind: str) -> None:
    values: dict[str, Any] = {}
    if kind == "none":
        values["scope"] = "none"
    elif kind == "title_only":
        values["paragraphs"] = (Paragraph(text=TITLE),)
    elif kind == "duplicate":
        values["canonical_content_id"] = 99
    else:
        values["metadata"] = ContentMetadata(
            form="article",
            genre="news",
            times=(
                ContentTime(
                    kind="original",
                    precision="time",
                    at=NOW - timedelta(days=30),
                    basis="synthetic",
                ),
            ),
        )
        if kind == "old_brief":
            values["scope"] = "complete_brief"
    gen, review = FakeClient(draft()), FakeClient(approval())
    with Session() as session:
        result = organize(session, gen, review, input_content(**values), now=NOW)
    assert result.status == "rejected" and gen.calls == review.calls == 0


def test_knowledge_and_review_do_not_expire_like_briefs() -> None:
    content = input_content(
        metadata=ContentMetadata(
            form="article",
            genre="knowledge",
            times=(
                ContentTime(
                    kind="original",
                    precision="date",
                    on=NOW.date() - timedelta(days=1000),
                    basis="synthetic",
                ),
            ),
        )
    )
    assert cheap_exclusion(content, NOW) is None
    with Session() as session:
        result = organize(
            session,
            FakeClient(draft()),
            FakeClient(approval()),
            content,
            now=NOW,
        )
    assert (
        result.status == "ready"
        and result.payload["current_value_reason"] == "evergreen_supported_material"
    )


@pytest.mark.parametrize("fault", ["quote", "language"])
def test_invalid_or_unattributed_claim_cannot_reach_paid_review(fault: str) -> None:
    content = input_content()
    out = draft()
    if fault == "quote":
        out["claims"][0]["quote"] = "Never present in the supplied body."
    else:
        out["title_zh"] = "English only generic title"
    review = FakeClient(approval())
    with Session() as session:
        result = organize(session, FakeClient(out), review, content, now=NOW)
    assert result.status == "failed" and review.calls == 0


def test_semantic_rejection_is_technical_failure_and_draft_resumes_without_generation() -> None:
    gen = FakeClient(draft())
    review = FakeClient(approval(False))
    saved: list[dict[str, Any]] = []
    with Session() as session:
        result = organize(session, gen, review, input_content(), checkpoint=saved.append, now=NOW)
    assert (
        result.status == "failed"
        and result.reason == "semantic_review_failed"
        and saved == [draft()]
    )
    gen = FakeClient({})
    with Session() as session:
        retried = organize(
            session,
            gen,
            FakeClient(approval()),
            input_content(),
            draft=saved[0],
            now=NOW,
        )
    assert retried.status == "ready" and gen.calls == 0


def test_prompt_context_stays_identical_after_jsonb_key_order_and_retry() -> None:
    content = input_content()
    out = draft()
    reordered = dict(reversed(list(out.items())))
    assert request_context(content, out) == request_context(content, reordered)
    assert processing_fingerprint(content, "card") != processing_fingerprint(content, "guide")
    corrected = content.model_copy(
        update={"metadata": ContentMetadata(form="article", publisher="Corrected")}
    )
    assert processing_fingerprint(content, "card") != processing_fingerprint(corrected, "card")


def test_short_guide_is_truthfully_unavailable_without_models() -> None:
    gen, review = FakeClient({}), FakeClient({})
    with Session() as session:
        result = organize(
            session, gen, review, input_content(), kind="guide", card=draft(), now=NOW
        )
    assert result.reason == "insufficient_increment" and gen.calls == review.calls == 0


def persisted_content(session: Session) -> ContentInput:
    metadata = {"title": TITLE, **ContentMetadata(form="article").model_dump(mode="json")}
    article = Article(
        title=TITLE,
        url="https://example.org/synthetic-r1-content",
        source_id="synthetic-r1",
        lang="zh",
        processing_track="r1",
        r1_metadata=metadata,
        metadata_fingerprint=fingerprint(metadata),
    )
    session.add(article)
    session.flush()
    material = ContentMaterial(
        article_id=article.id,
        scope="open_text_unit",
        access_status="ok",
        completeness="observed_unit",
        completeness_basis="synthetic",
        source_url=article.url,
        retrieved_at=NOW,
        input_fingerprint="body-v1",
        metadata_fingerprint=article.metadata_fingerprint,
        extractor_version="synthetic-v1",
        schema_version="synthetic",
        paragraphs=[{"text": TEXT}],
        evidence={},
    )
    session.add(material)
    session.flush()
    article.current_material_id = material.id
    session.flush()
    from unspun.pipeline.content_processing import load_content

    return load_content(session, article.id)


def test_real_postgres_persists_three_reviewed_versions_without_legacy_mutation(
    db_session: Session,
) -> None:
    content = persisted_content(db_session)
    with Session() as disconnected:
        result = organize(
            disconnected,
            FakeClient(draft()),
            FakeClient(approval()),
            content,
            now=NOW,
        )
    assert apply_processing(db_session, result)["status"] == "ready"
    rows = list(
        db_session.scalars(
            select(ContentDerivation).where(ContentDerivation.article_id == content.article_id)
        )
    )
    assert {r.kind for r in rows} == {"features", "admission", "card"}
    assert all(
        r.status == "ready" and r.review_evidence and r.review_evidence["approved"] for r in rows
    )
    article = db_session.get(Article, content.article_id)
    assert (
        article
        and article.event_id is None
        and article.summary_zh is None
        and article.embedding is None
    )
    first = enqueue_processing(db_session, content.article_id, "guide")
    assert enqueue_processing(db_session, content.article_id, "guide") == first
    lease = claim(db_session, queue="guide", kinds={"process_guide"}, worker="synthetic")
    assert lease and lease.article_id == content.article_id


def test_corrected_material_discards_stale_generation(db_session: Session) -> None:
    content = persisted_content(db_session)
    with Session() as disconnected:
        result = organize(
            disconnected,
            FakeClient(draft()),
            FakeClient(approval()),
            content,
            now=NOW,
        )
    article = db_session.get(Article, content.article_id)
    assert article
    article.title = TITLE + " updated"
    db_session.flush()
    assert apply_processing(db_session, result)["stale_result"] is True
    assert not db_session.scalar(
        select(ContentDerivation.id).where(ContentDerivation.article_id == content.article_id)
    )


def test_committed_draft_survives_budget_deferral_and_restart(
    ingestion_db: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy import update

    from unspun.core.billing import BudgetExceeded
    from unspun.core.task_models import PipelineTask
    from unspun.pipeline.content_processing import ContentHandler
    from unspun.pipeline.r1_worker import process_one

    source = ingestion_db.source(paid=True)
    with ingestion_db.scope() as session:
        content = persisted_content(session)
        article = session.get(Article, content.article_id)
        assert article
        article.source_id = source.id
        session.flush()
        task_id = enqueue_processing(session, article.id)
    calls: list[str] = []
    allowed = False

    class NetworkClient(FakeClient):
        def __init__(self, *, context: Any) -> None:
            self.phase = context.phase

        def __enter__(self) -> "NetworkClient":
            return self

        def __exit__(self, *args: Any) -> None:
            pass

        def chat_json(self, session: Session, **kwargs: Any) -> dict[str, Any]:
            assert not session.in_transaction()
            calls.append(self.phase)
            if self.phase == "review":
                if not allowed:
                    raise BudgetExceeded("synthetic rolling cap")
                return approval()
            return draft()

    monkeypatch.setattr("unspun.pipeline.content_processing.LlmClient", NetworkClient)
    handler = ContentHandler({source.id: source}, scope=ingestion_db.scope)
    assert process_one(
        "paid", {("paid", "process_card"): handler}, worker="before", scope=ingestion_db.scope
    )
    with ingestion_db.scope() as session:
        task = session.get(PipelineTask, task_id)
        assert task
        assert task.status == "budget_deferred" and task.failures == 0
        saved = session.scalar(
            select(ContentDerivation).where(ContentDerivation.article_id == content.article_id)
        )
        assert saved and saved.status == "budget_deferred" and saved.payload == {"draft": draft()}
        session.execute(
            update(PipelineTask)
            .where(PipelineTask.id == task_id)
            .values(due_at=NOW - timedelta(days=1))
        )
    allowed = True
    assert process_one(
        "paid",
        {("paid", "process_card"): handler},
        worker="after-restart",
        scope=ingestion_db.scope,
    )
    assert calls == ["generate", "review", "review"]
    with ingestion_db.scope() as session:
        assert session.get(PipelineTask, task_id).status == "completed"
        assert all(
            row.status == "ready"
            for row in session.scalars(
                select(ContentDerivation).where(ContentDerivation.article_id == content.article_id)
            )
        )


# Reuse the committed-row fixture and its exact synthetic-identity cleanup.
from tests.test_ingestion import ingestion_db as ingestion_db  # noqa: E402


def test_review_selects_only_supported_claims_and_keeps_full_rejected_evidence() -> None:
    out = draft(reading_value=2)
    other = {
        "text": TEXT + "\u8fd8\u9700\u8981\u7ee7\u7eed\u9a8c\u8bc1\u3002",
        "quote": TEXT,
        "voice": "reported",
    }
    out["claims"].append(other)
    response = approval()
    response["claim_checks"].append(
        {"index": 1, "supported": False, "reason": "Unsupported additional assertion"}
    )
    with Session() as session:
        result = organize(session, FakeClient(out), FakeClient(response), input_content(), now=NOW)
    assert result.status == "ready" and len(result.payload["claims"]) == 1
    assert result.payload["reading_value"] == 1
    assert result.review["generation_output"] == out
    assert result.review["published_claim_indices"] == [0]


@pytest.mark.parametrize(
    "checks",
    [
        [],
        [{"index": 0, "supported": True}, {"index": 0, "supported": False}],
        [{"index": True, "supported": True}],
        [{"index": 0, "supported": "true"}],
    ],
)
def test_missing_or_ambiguous_review_claim_results_fail_closed(
    checks: list[dict[str, Any]],
) -> None:
    response = approval()
    response["claim_checks"] = checks
    with Session() as session:
        result = organize(
            session, FakeClient(draft()), FakeClient(response), input_content(), now=NOW
        )
    assert result.status == "failed" and result.review["approved"] is False


def test_reverted_version_restores_all_three_results_and_never_revives_alias(
    db_session: Session,
) -> None:
    content = persisted_content(db_session)
    with Session() as session:
        result = organize(session, FakeClient(draft()), FakeClient(approval()), content, now=NOW)
    apply_processing(db_session, result)
    versions = list(
        db_session.scalars(
            select(ContentDerivation).where(ContentDerivation.article_id == content.article_id)
        )
    )
    for row in versions:
        row.status = "invalidated"
    enqueue_processing(db_session, content.article_id)
    assert {row.status for row in versions} == {"ready"}
    root = Article(
        title="Root",
        url="https://example.org/canonical-other",
        source_id="synthetic-r1",
        processing_track="r1",
    )
    db_session.add(root)
    db_session.flush()
    article = db_session.get(Article, content.article_id)
    assert article
    article.canonical_content_id = root.id
    for row in versions:
        row.status = "invalidated"
    enqueue_processing(db_session, content.article_id)
    assert {row.status for row in versions} == {"rejected"}
    assert {row.reason for row in versions} == {"canonical_duplicate"}


def test_guide_wait_is_a_dependency_without_fault_or_budget_rejection(ingestion_db: Any) -> None:
    from unspun.core.task_models import PipelineTask
    from unspun.pipeline.content_processing import ContentHandler
    from unspun.pipeline.r1_worker import process_one

    source = ingestion_db.source(paid=True)
    with ingestion_db.scope() as session:
        content = persisted_content(session)
        article = session.get(Article, content.article_id)
        assert article
        article.source_id = source.id
        task_id = enqueue_processing(session, content.article_id, "guide")
    handler = ContentHandler({source.id: source}, kind="guide", scope=ingestion_db.scope)
    assert process_one(
        "guide", {("guide", "process_guide"): handler}, worker="wait-card", scope=ingestion_db.scope
    )
    with ingestion_db.scope() as session:
        task = session.get(PipelineTask, task_id)
        assert task
        assert task.status == "retry_wait" and task.failures == 0
        row = session.scalar(
            select(ContentDerivation).where(ContentDerivation.article_id == content.article_id)
        )
        assert row and row.status == "pending" and row.reason == "card_pending"


def test_semantic_failure_is_a_failed_task_attempt_with_retained_evidence(
    ingestion_db: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy import update

    from unspun.core.task_models import PipelineTask
    from unspun.pipeline.content_processing import ContentHandler
    from unspun.pipeline.r1_worker import process_one

    source = ingestion_db.source(paid=True)
    with ingestion_db.scope() as session:
        content = persisted_content(session)
        article = session.get(Article, content.article_id)
        assert article
        article.source_id = source.id
        task_id = enqueue_processing(session, article.id)

    class NetworkClient(FakeClient):
        def __init__(self, *, context: Any) -> None:
            self.phase = context.phase

        def __enter__(self) -> "NetworkClient":
            return self

        def __exit__(self, *args: Any) -> None:
            pass

        def chat_json(self, session: Session, **kwargs: Any) -> dict[str, Any]:
            assert not session.in_transaction()
            return draft() if self.phase == "generate" else approval(False)

    monkeypatch.setattr("unspun.pipeline.content_processing.LlmClient", NetworkClient)
    handler = ContentHandler({source.id: source}, scope=ingestion_db.scope)
    for expected_failures in [1, 2, 3]:
        assert process_one(
            "paid",
            {("paid", "process_card"): handler},
            worker="failure-probe",
            scope=ingestion_db.scope,
        )
        with ingestion_db.scope() as session:
            task = session.get(PipelineTask, task_id)
            assert task
            assert task.failures == expected_failures
            assert task.status == ("failed" if expected_failures == 3 else "retry_wait")
            rows = list(
                session.scalars(
                    select(ContentDerivation).where(
                        ContentDerivation.article_id == content.article_id
                    )
                )
            )
            assert len(rows) == 3 and all(
                row.status == "failed" and row.review_evidence for row in rows
            )
            session.execute(
                update(PipelineTask)
                .where(PipelineTask.id == task_id)
                .values(due_at=NOW - timedelta(days=1))
            )
