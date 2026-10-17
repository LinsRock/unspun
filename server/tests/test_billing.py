"""Physical HTTP attempts with independently committed PostgreSQL accounting."""

import os
import subprocess
import sys
import threading
import uuid
from collections.abc import Callable, Generator, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy import Engine, create_engine, delete, func, select
from sqlalchemy.orm import Session

from unspun.core.billing import (
    EVALUATION_LIMIT,
    BudgetExceeded,
    CallContext,
    DatabaseJournal,
    UsageUnknown,
    budget_status,
    initialize_budget,
    reservation_bound,
)
from unspun.core.billing_models import BilledRequest, BudgetCarry, BudgetPolicy
from unspun.core.config import get_settings
from unspun.core.llm import LlmClient, LlmError
from unspun.core.models import EMBEDDING_DIM, Article, LlmUsage
from unspun.core.task_models import PipelineTask, TaskAttempt
from unspun.core.tasks import claim, enqueue

MODEL = "google/gemini-2.5-flash-lite"
REQUEST: dict[str, Any] = {"messages": [{"content": "test"}], "max_tokens": 1024}


@dataclass
class BillingDB:
    engine: Engine
    journal: DatabaseJournal

    def reserve(self, context: CallContext | None = None, purpose: str = "summary") -> str:
        return self.journal.reserve(
            purpose=purpose, model=MODEL, request=REQUEST, context=context or CallContext()
        ).id

    def policy(self, **values: Any) -> None:
        with Session(self.engine) as session, session.begin():
            policy = session.get(BudgetPolicy, 1)
            assert policy
            for key, value in values.items():
                setattr(policy, key, value)

    def requests(self) -> list[BilledRequest]:
        with Session(self.engine) as session:
            return list(session.scalars(select(BilledRequest).order_by(BilledRequest.started_at)))

    def usage(self) -> list[LlmUsage]:
        with Session(self.engine) as session:
            return list(session.scalars(select(LlmUsage).order_by(LlmUsage.id)))


@pytest.fixture
def billing_db(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> Generator[BillingDB]:
    assert os.environ.get("UNSPUN_DATABASE_URL"), "an explicit migrated isolated DB is required"
    monkeypatch.setenv("UNSPUN_OPENROUTER_API_KEY", "synthetic-billing-key")
    get_settings.cache_clear()
    engine = create_engine(get_settings().database_url, pool_size=8)
    with Session(engine) as session, session.begin():
        assert session.get(BudgetPolicy, 1) is None
        assert session.scalar(select(func.count()).select_from(BilledRequest)) == 0
        existing_usage = set(session.scalars(select(LlmUsage.id)))
        existing_tasks = set(session.scalars(select(PipelineTask.id)))
        existing_articles = set(session.scalars(select(Article.id)))
        initialize_budget(session, scope="evaluation")
    yield BillingDB(engine, DatabaseJournal(engine))
    with Session(engine) as session, session.begin():
        session.execute(delete(BilledRequest))
        task_ids = select(PipelineTask.id).where(PipelineTask.id.not_in(existing_tasks))
        session.execute(delete(TaskAttempt).where(TaskAttempt.task_id.in_(task_ids)))
        session.execute(delete(PipelineTask).where(PipelineTask.id.not_in(existing_tasks)))
        session.execute(delete(Article).where(Article.id.not_in(existing_articles)))
        session.execute(delete(BudgetPolicy).where(BudgetPolicy.id == 1))
        session.execute(delete(BudgetCarry))
        session.execute(delete(LlmUsage).where(LlmUsage.id.not_in(existing_usage)))
    engine.dispose()
    get_settings.cache_clear()


def reply(content: str = "{}", cost: Any = 0.001, **usage: Any) -> dict[str, Any]:
    return {
        "id": "synthetic-generation",
        "choices": [{"finish_reason": "stop", "message": {"content": content}}],
        "usage": {"cost": cost, "prompt_tokens": 10, "completion_tokens": 5, **usage},
    }


def invoke(
    db: BillingDB,
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    purpose: str = "summary",
    context: CallContext | None = None,
) -> dict[str, Any]:
    with (
        Session(db.engine) as session,
        LlmClient(transport=httpx.MockTransport(handler), context=context) as client,
    ):
        return client.chat_json(session, model=MODEL, system="test", user="test", purpose=purpose)


def test_atomic_two_consumers_cannot_spend_same_balance(billing_db: BillingDB) -> None:
    billing_db.policy(monthly_limit_usd=reservation_bound(MODEL, REQUEST) + Decimal("0.001"))
    barrier = threading.Barrier(2)

    def reserve() -> str:
        barrier.wait(timeout=5)
        try:
            return billing_db.reserve()
        except BudgetExceeded:
            return "blocked"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(reserve) for _ in range(2)]
        results = [future.result(timeout=10) for future in futures]
    assert results.count("blocked") == 1
    assert len(billing_db.requests()) == 1


def test_budget_rejection_sends_no_http_even_for_legacy(billing_db: BillingDB) -> None:
    billing_db.policy(monthly_limit_usd=0)

    def forbidden(_: httpx.Request) -> httpx.Response:
        pytest.fail("budget rejection must happen before HTTP")

    with pytest.raises(BudgetExceeded):
        invoke(billing_db, forbidden)
    assert not billing_db.requests() and not billing_db.usage()


def test_allocation_revision_requires_cutover_and_keeps_unknown_holds(
    billing_db: BillingDB,
) -> None:
    billing_db.policy(monthly_limit_usd=Decimal("0.60"))
    with Session(billing_db.engine) as session, session.begin():
        session.add(
            LlmUsage(
                purpose="summary",
                model=MODEL,
                cost_usd=0.29,
                created_at=datetime.now(UTC),
            )
        )
    for model in (MODEL, MODEL, MODEL, "google/gemini-2.5-flash"):
        reservation = billing_db.journal.reserve(
            purpose="summary", model=model, request=REQUEST, context=CallContext()
        )
        billing_db.journal.unknown(reservation.id, "retained transport uncertainty")
    held = {r.id: r.reserved_usd for r in billing_db.requests()}
    review: dict[str, Any] = {
        "purpose": "grounding",
        "model": "google/gemini-2.5-flash",
        "request": REQUEST,
    }
    # A code release does not silently enlarge an existing policy row.
    with pytest.raises(BudgetExceeded, match="monthly budget"):
        billing_db.journal.reserve(**review, context=CallContext())
    billing_db.policy(monthly_limit_usd=EVALUATION_LIMIT)
    billing_db.journal.reserve(**review, context=CallContext())
    rows = billing_db.requests()
    assert {r.id: r.reserved_usd for r in rows if r.status == "usage_unknown"} == held
    assert len(rows) == 5 and len(billing_db.usage()) == 1
    assert billing_db.usage()[0].cost_usd == 0.29


def test_evaluation_review_increase_cannot_raise_production_ceiling(billing_db: BillingDB) -> None:
    get_settings().grounding_budget_24h_usd = 1.0
    for _ in range(2):
        reservation = billing_db.journal.reserve(
            purpose="grounding",
            model="google/gemini-2.5-flash",
            request=REQUEST,
            context=CallContext(),
        )
        billing_db.journal.unknown(reservation.id, "retained rejection without provider cost")
    held = {r.id: r.reserved_usd for r in billing_db.requests()}
    billing_db.policy(
        scope="production", monthly_limit_usd=Decimal("14"), stage_caps={"legacy": "14"}
    )
    with pytest.raises(BudgetExceeded, match="rolling grounding"):
        billing_db.journal.reserve(
            purpose="grounding",
            model="google/gemini-2.5-flash",
            request=REQUEST,
            context=CallContext(),
        )
    billing_db.policy(scope="evaluation", monthly_limit_usd=EVALUATION_LIMIT, stage_caps={})
    billing_db.journal.reserve(
        purpose="grounding",
        model="google/gemini-2.5-flash",
        request=REQUEST,
        context=CallContext(),
    )
    assert {
        r.id: r.reserved_usd for r in billing_db.requests() if r.status == "usage_unknown"
    } == held
    assert len(billing_db.requests()) == 3


def test_fee_survives_json_failure_and_business_rollback(billing_db: BillingDB) -> None:
    with (
        Session(billing_db.engine) as session,
        LlmClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=reply("not JSON")))
        ) as client,
    ):
        with pytest.raises(ValueError):
            client.chat_json(session, model=MODEL, system="s", user="u", purpose="summary")
        session.rollback()
    assert len(billing_db.usage()) == 1
    assert billing_db.requests()[0].usage_id == billing_db.usage()[0].id
    assert billing_db.usage()[0].cost_usd == 0.001


def test_business_failure_after_valid_response_still_has_one_fee(billing_db: BillingDB) -> None:
    with (
        pytest.raises(RuntimeError, match="business"),
        Session(billing_db.engine) as session,
        session.begin(),
        LlmClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=reply()))
        ) as client,
    ):
        assert client.chat_json(session, model=MODEL, system="s", user="u", purpose="summary") == {}
        raise RuntimeError("business write failed")
    assert len(billing_db.usage()) == 1


def test_truncation_retry_has_two_physical_fees(billing_db: BillingDB) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        data = reply('{"cut' if attempts == 1 else "{}")
        data["choices"][0]["finish_reason"] = "length" if attempts == 1 else "stop"
        return httpx.Response(200, json=data)

    assert invoke(billing_db, handler) == {}
    assert attempts == len(billing_db.requests()) == len(billing_db.usage()) == 2


@pytest.mark.parametrize("cost", [None, -1, "NaN", True])
def test_missing_or_invalid_cost_retains_hold_not_zero(billing_db: BillingDB, cost: Any) -> None:
    with pytest.raises(UsageUnknown):
        invoke(
            billing_db,
            lambda _: httpx.Response(200, json=reply(cost=cost)),
            context=CallContext(logical_key="same-operation"),
        )
    row = billing_db.requests()[0]
    assert row.status == "usage_unknown" and row.reserved_usd > 0
    assert not billing_db.usage()
    with pytest.raises(UsageUnknown):
        invoke(
            billing_db,
            lambda _: pytest.fail("unknown request must not be repeated"),
            context=CallContext(logical_key="same-operation"),
        )


def test_network_interruption_retains_reservation_and_next_month_hold(
    billing_db: BillingDB,
) -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("synthetic interrupted reply", request=request)

    with pytest.raises(httpx.ReadTimeout):
        invoke(billing_db, timeout)
    with Session(billing_db.engine) as session, session.begin():
        row = session.get(BilledRequest, billing_db.requests()[0].id)
        assert row
        row.started_at = datetime.now(UTC) - timedelta(days=40)
    billing_db.policy(monthly_limit_usd=reservation_bound(MODEL, REQUEST) + Decimal("0.001"))
    with pytest.raises(BudgetExceeded):
        billing_db.reserve()
    assert not billing_db.usage()


def test_missing_tokens_remain_unknown_and_known_fee_settles_once(billing_db: BillingDB) -> None:
    identity = billing_db.reserve()
    data = reply(prompt_tokens=None, completion_tokens=None)
    assert billing_db.journal.finish(identity, data, 200)
    assert billing_db.journal.finish(identity, data, 200)
    row = billing_db.usage()[0]
    assert len(billing_db.usage()) == 1
    assert row.prompt_tokens is None and row.completion_tokens is None


def test_generation_reconciliation_is_identified_idempotent_and_reusable(
    billing_db: BillingDB,
) -> None:
    context = CallContext(logical_key="reconcile")
    with pytest.raises(UsageUnknown):
        invoke(billing_db, lambda _: httpx.Response(200, json=reply(cost=None)), context=context)
    identity = billing_db.requests()[0].id
    with pytest.raises(LlmError, match="does not match"):
        billing_db.journal.reconcile(identity, {"id": "other", "total_cost": 0})
    evidence = {
        "id": "synthetic-generation",
        "total_cost": 0.002,
        "native_tokens_prompt": 20,
        "native_tokens_completion": 10,
    }
    assert billing_db.journal.reconcile(identity, evidence)
    assert billing_db.journal.reconcile(identity, evidence)
    assert (
        invoke(
            billing_db, lambda _: pytest.fail("settled response must be reused"), context=context
        )
        == {}
    )
    assert len(billing_db.usage()) == 1 and billing_db.usage()[0].cost_usd == 0.002
    assert billing_db.requests()[0].reconciliation


def test_anonymous_timeout_cannot_be_declared_free(billing_db: BillingDB) -> None:
    identity = billing_db.reserve()
    billing_db.journal.unknown(identity, "timeout")
    with pytest.raises(UsageUnknown, match="no provider"):
        billing_db.journal.reconcile(identity, {"total_cost": 0})
    assert billing_db.requests()[0].status == "usage_unknown"


def test_interrupted_body_keeps_header_id_and_settles_without_a_result(
    billing_db: BillingDB,
) -> None:
    generation_id = "gen-interrupted-body"
    context = CallContext(logical_key="header-recovery")

    class InterruptedBody(httpx.SyncByteStream):
        def __iter__(self) -> Iterator[bytes]:
            # The independently committed header must survive process/body failure.
            row = billing_db.requests()[0]
            assert row.provider_generation_id == generation_id and row.http_status == 200
            assert row.response_payload is None and not billing_db.usage()
            yield b'{"id":"gen-interrupted-body",'
            raise httpx.RemoteProtocolError("synthetic incomplete body")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"X-Generation-Id": generation_id}, stream=InterruptedBody()
        )

    with pytest.raises(httpx.RemoteProtocolError):
        invoke(billing_db, handler, context=context)
    row = billing_db.requests()[0]
    assert row.status == "usage_unknown" and row.http_status == 200
    assert row.provider_generation_id == generation_id and not billing_db.usage()
    evidence = {"id": generation_id, "total_cost": 0.002}
    billing_db.journal.reconcile(row.id, evidence)
    with Session(billing_db.engine) as session, session.begin():
        audited = session.get(BilledRequest, row.id)
        assert audited and audited.reconciliation
        audited.reconciliation = {**audited.reconciliation, "association": "retained-audit"}
    billing_db.journal.reconcile(row.id, evidence)
    settled = billing_db.requests()[0]
    assert settled.status == "settled_without_result" and settled.http_status == 200
    assert settled.reconciliation and settled.reconciliation["original_response"] is None
    assert settled.reconciliation["association"] == "retained-audit"
    assert settled.error == "RemoteProtocolError"
    assert len(billing_db.usage()) == 1 and billing_db.usage()[0].cost_usd == 0.002
    # Fee confirmation cannot turn the absent output into a reusable success.
    assert billing_db.reserve(context) != row.id


def test_header_id_survives_missing_body_id_and_unknown_cost(billing_db: BillingDB) -> None:
    payload = reply(cost=None)
    del payload["id"]
    generation_id = "gen-header-only"
    context = CallContext(logical_key="header-only")
    with pytest.raises(UsageUnknown):
        invoke(
            billing_db,
            lambda _: httpx.Response(200, headers={"X-Generation-Id": generation_id}, json=payload),
            context=context,
        )
    row = billing_db.requests()[0]
    assert row.provider_generation_id == generation_id
    billing_db.journal.reconcile(row.id, {"id": generation_id, "total_cost": 0.002})
    assert (
        invoke(
            billing_db, lambda _: pytest.fail("complete response must be reused"), context=context
        )
        == {}
    )
    assert len(billing_db.usage()) == 1


def test_header_body_id_mismatch_retains_hold_without_charging(billing_db: BillingDB) -> None:
    with pytest.raises(LlmError, match="does not match its header"):
        invoke(
            billing_db,
            lambda _: httpx.Response(200, headers={"X-Generation-Id": "gen-header"}, json=reply()),
        )
    row = billing_db.requests()[0]
    assert row.status == "usage_unknown" and row.provider_generation_id == "gen-header"
    assert not billing_db.usage()


def test_header_identifier_cannot_change_or_belong_to_two_requests(billing_db: BillingDB) -> None:
    first, second = billing_db.reserve(), billing_db.reserve()
    billing_db.journal.identify(first, "gen-unique", 200)
    billing_db.journal.identify(first, "gen-unique", 200)
    with pytest.raises(LlmError, match="identifier changed"):
        billing_db.journal.identify(first, "gen-different", 200)
    with pytest.raises(LlmError, match="another request"):
        billing_db.journal.identify(second, "gen-unique", 200)
    assert not billing_db.usage()


def test_known_http_failure_billed_then_explicit_retry_allowed(billing_db: BillingDB) -> None:
    context = CallContext(logical_key="retry-http")
    with pytest.raises(httpx.HTTPStatusError):
        invoke(billing_db, lambda _: httpx.Response(500, json=reply()), context=context)
    assert invoke(billing_db, lambda _: httpx.Response(200, json=reply()), context=context) == {}
    assert len(billing_db.usage()) == 2


def test_actual_overrun_is_recorded_before_pausing(billing_db: BillingDB) -> None:
    with pytest.raises(BudgetExceeded, match="exceeded reservation"):
        invoke(billing_db, lambda _: httpx.Response(200, json=reply(cost=0.5)))
    assert billing_db.usage()[0].cost_usd == 0.5
    with Session(billing_db.engine) as session:
        assert not budget_status(session)["enabled"]
    with pytest.raises(BudgetExceeded):
        billing_db.reserve()


def test_embeddings_split_into_individually_billed_bounded_requests(billing_db: BillingDB) -> None:
    import json

    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        data = json.loads(request.content)
        assert sum(len(text.encode()) for text in data["input"]) <= 32768
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": i, "embedding": [1.0] * EMBEDDING_DIM}
                    for i in range(len(data["input"]))
                ],
                "usage": {"cost": 0.00001, "prompt_tokens": 5},
            },
        )

    with (
        Session(billing_db.engine) as session,
        LlmClient(transport=httpx.MockTransport(handler)) as client,
    ):
        assert len(client.embed(session, ["x" * 20000] * 3)) == 3
    assert calls == len(billing_db.requests()) == len(billing_db.usage()) == 3
    assert all(row.stage == "embedding" for row in billing_db.requests())


def test_grounding_has_additional_atomic_cap(billing_db: BillingDB) -> None:
    amount = reservation_bound(MODEL, REQUEST)
    billing_db.reserve(purpose="grounding")
    get_settings().grounding_budget_24h_usd = float(amount + Decimal("0.001"))
    with pytest.raises(BudgetExceeded, match="grounding"):
        billing_db.reserve(purpose="grounding")


def test_lower_existing_key_limit_and_changed_key_fail_closed(billing_db: BillingDB) -> None:
    billing_db.policy(
        scope="production",
        provider_limit_usd=10,
        provider_usage_usd=Decimal("9.39"),
        provider_limit_kind="monthly",
        stage_caps={"legacy": "19.40"},
    )
    with pytest.raises(BudgetExceeded, match="provider key limit"):
        billing_db.reserve()
    billing_db.policy(provider_usage_usd=0, key_fingerprint="changed")
    with pytest.raises(BudgetExceeded, match="key changed"):
        billing_db.reserve()


def test_production_r1_call_requires_content_lease(billing_db: BillingDB) -> None:
    billing_db.policy(scope="production")
    with pytest.raises(LlmError, match="content task lease"):
        billing_db.reserve(context=CallContext(stage="card"))


def test_unregistered_model_cannot_initiate_request(billing_db: BillingDB) -> None:
    with pytest.raises(BudgetExceeded, match="registered price"):
        billing_db.journal.reserve(
            purpose="summary", model="unregistered", request=REQUEST, context=CallContext()
        )


def test_task_attempt_content_links_and_stale_lease_fence(billing_db: BillingDB) -> None:
    with Session(billing_db.engine) as session, session.begin():
        article = Article(
            source_id="synthetic",
            title="billing probe",
            url=f"https://example.org/{uuid.uuid4().hex}",
            processing_track="r1",
        )
        session.add(article)
        session.flush()
        enqueue(
            session,
            queue="paid",
            kind="billing-probe",
            object_key=f"content:{article.id}",
            article_id=article.id,
            source_id="synthetic",
            input_fingerprint="test",
            strategy_version="test",
            payload={},
        )
        lease = claim(session, queue="paid", kinds={"billing-probe"}, worker="billing-test")
        assert lease
    billing_db.policy(scope="production", stage_caps={"card": "10"})
    identity = billing_db.reserve(
        context=CallContext(stage="card", phase="generation", lease=lease)
    )
    row = billing_db.requests()[0]
    assert row.task_id == lease.task_id and row.task_attempt_id == lease.attempt_id
    assert row.article_id == lease.article_id and row.source_id == "synthetic"
    billing_db.journal.finish(identity, reply(), 200)
    with Session(billing_db.engine) as session, session.begin():
        task = session.get(PipelineTask, lease.task_id)
        assert task
        task.lease_until = datetime.now(UTC) - timedelta(seconds=1)
    with pytest.raises(LlmError, match="stale task"):
        billing_db.reserve(context=CallContext(stage="card", lease=lease))


@pytest.mark.parametrize("after_response", [False, True])
def test_process_exit_does_not_erase_request_or_fee(
    billing_db: BillingDB, after_response: bool
) -> None:
    script = r"""
import os
import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from unspun.core.config import get_settings
from unspun.core.llm import LlmClient
engine = create_engine(get_settings().database_url)
def handler(request):
    if os.environ['BILLING_EXIT_AFTER_REPLY'] == '0':
        os._exit(37)
    return httpx.Response(200, json={
        'choices':[{'message':{'content':'{}'},'finish_reason':'stop'}],
        'usage':{'cost':0.001,'prompt_tokens':1,'completion_tokens':1}})
with Session(engine) as session, LlmClient(transport=httpx.MockTransport(handler)) as client:
    client.chat_json(session, model='google/gemini-2.5-flash-lite',
                     system='s', user='u', purpose='summary')
    os._exit(37)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, "BILLING_EXIT_AFTER_REPLY": "1" if after_response else "0"},
        timeout=20,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 37, result.stderr
    rows = billing_db.requests()
    assert len(rows) == 1
    assert rows[0].status == ("responded" if after_response else "reserved")
    assert len(billing_db.usage()) == int(after_response)


def test_monthly_key_uses_monthly_counter_even_after_large_lifetime_spend(
    billing_db: BillingDB,
) -> None:
    with Session(billing_db.engine) as session, session.begin():
        session.execute(delete(BudgetPolicy))
        session.execute(delete(BudgetCarry))
        initialize_budget(
            session,
            scope="production",
            provider_monthly_usd=Decimal("1"),
            provider_usage_usd=Decimal("12"),
            provider_limit_usd=Decimal("10"),
            provider_limit_kind="monthly",
        )
    assert billing_db.reserve()


@pytest.mark.parametrize("run_budget, max_calls", [(0.031, 10), (0.6, 1)])
def test_live_evaluation_counts_physical_retries_and_stops_before_next_http(
    billing_db: BillingDB, run_budget: float, max_calls: int
) -> None:
    from unspun.evaluation.run_quality import BudgetedClient, BudgetLedger

    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        data = reply('{"cut', cost=0.005)
        data["choices"][0]["finish_reason"] = "length"
        return httpx.Response(200, json=data)

    ledger = BudgetLedger(run_budget, max_calls)
    client = BudgetedClient(ledger, transport=httpx.MockTransport(handler))
    try:
        with Session(billing_db.engine) as session, pytest.raises(BudgetExceeded):
            client.chat_json(session, model=MODEL, system="s", user="u", purpose="summary")
    finally:
        client.client.close()
    assert calls == ledger.calls == len(billing_db.usage()) == 1
    assert ledger.cost_usd == 0.005


def test_evaluation_allocation_does_not_reset_when_calendar_month_changes(
    billing_db: BillingDB,
) -> None:
    identity = billing_db.reserve()
    billing_db.journal.finish(identity, reply(cost=0.02), 200)
    before = datetime.now(UTC) - timedelta(days=40)
    billing_db.policy(coverage_started_at=before, monthly_limit_usd=Decimal("0.03"))
    with Session(billing_db.engine) as session, session.begin():
        row = session.get(LlmUsage, billing_db.usage()[0].id)
        assert row
        row.created_at = before + timedelta(days=1)
    with pytest.raises(BudgetExceeded):
        billing_db.reserve()


@pytest.mark.anyio
async def test_cost_api_keeps_known_totals_links_and_unknowns_separate(
    billing_db: BillingDB,
) -> None:
    from unspun.api.app import app
    from unspun.api.events import get_db
    from unspun.core.config import Settings

    first = billing_db.reserve()
    billing_db.journal.finish(first, reply(), 200)
    second = billing_db.reserve()
    billing_db.journal.unknown(second, "synthetic timeout")

    def override() -> Generator[Session]:
        with Session(billing_db.engine) as session:
            yield session

    app.dependency_overrides[get_db] = override
    app.dependency_overrides[get_settings] = lambda: Settings(admin_local_preview=True)
    params = {"start": "2026-10-15T00:00:00Z", "end": "2026-10-18T00:00:00Z"}
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
        ) as client:
            costs = (await client.get("/api/admin/costs", params=params)).json()
            calls = (await client.get("/api/admin/costs/calls", params=params)).json()
            requests = (await client.get("/api/admin/costs/requests", params=params)).json()
        assert Decimal(costs["calls"]["cost_usd"]) == Decimal("0.001")
        assert costs["budget"]["enforcement"]["unresolved_calls"] == 1
        assert (
            costs["budget"]["enforcement"]["unit_costs"]["per_100_candidates"]["status"]
            == "unmeasured"
        )
        assert calls["items"][0]["request_id"] == first
        assert calls["items"][0]["association"] == "recorded"
        assert requests["total"] == 2
        assert {row["status"] for row in requests["items"]} == {"responded", "usage_unknown"}
    finally:
        app.dependency_overrides.clear()
