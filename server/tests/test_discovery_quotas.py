"""R2 scan bounds, fair selection, durable quotas and zero-provider recovery checks."""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_ingestion import IngestionDB, material
from tests.test_ingestion import ingestion_db as ingestion_db
from unspun.core.content import ContentMetadata, ContentTime
from unspun.core.sources import DiscoveryQuotas, Source, load_sources
from unspun.core.task_models import DiscoveryBatch, PipelineTask
from unspun.core.tasks import Lease, complete, fail
from unspun.pipeline.discovery import DiscoveryItem, DiscoveryResult, discover, persist_discovery
from unspun.pipeline.materials import MaterialHandler


def quota_source(db: IngestionDB, **quotas: int) -> Source:
    return db.source(quotas={"scan": 30, "material": 1, "paid": 1, **quotas}, paid=True)


def persist(db: IngestionDB, source: Source, *items: DiscoveryItem, cycle: str) -> dict[str, Any]:
    return db.persist(source, *items, cycle=cycle, now=datetime.now(UTC))


def finish(db: IngestionDB, source: Source, lease: Lease, body: str) -> dict[str, Any]:
    result = material(lease, body).model_copy(update={"retrieved_at": datetime.now(UTC)})
    with db.scope() as session:
        applied: dict[str, Any] = {}

        def apply(session: Session) -> dict[str, Any]:
            applied.update(MaterialHandler({source.id: source}).apply(session, lease, result))
            return applied

        assert complete(session, lease, apply=apply)
        return applied


def test_seen_first_does_not_hide_new_identity_and_replay_keeps_one_receipt(
    ingestion_db: IngestionDB,
) -> None:
    db = ingestion_db
    source, old, new = quota_source(db), db.item("old"), db.item("new")
    persist(db, source, old, cycle="seed")
    out = persist(db, source, old, new, new, cycle="poll")
    assert out["new_candidates"] == 1 and out["known_candidates"] == 1
    assert out["identity_duplicates"] == 1 and out["material_selected"] == 1
    replay = persist(db, source, old, new, cycle="poll")
    assert replay == {**out, "replayed": True}
    with db.scope() as session:
        assert session.scalar(select(func.count()).select_from(PipelineTask)) == 2
        assert session.scalar(select(func.count()).select_from(DiscoveryBatch)) == 2
    later = persist(db, source, old, new, db.item("between-polls"), cycle="later")
    assert later["new_candidates"] == later["material_selected"] == 1


def test_single_slot_alternates_due_updates_with_waiting_new_objects(
    ingestion_db: IngestionDB,
) -> None:
    db = ingestion_db
    source = quota_source(db, recheck_seconds=60)
    old, other, new = db.item("old"), db.item("other"), db.item("new")
    persist(db, source, old, cycle="seed")
    first = db.take()
    finish(db, source, first, "Original distinct source body. " * 8)
    persist(db, source, old, other, cycle="second")
    second = db.take()
    finish(db, source, second, "Other independently reported source body. " * 8)
    with db.scope() as session:
        for task_id in (first.task_id, second.task_id):
            task = session.get(PipelineTask, task_id)
            assert task
            task.created_at = datetime.now(UTC) - timedelta(hours=2)
    refreshed = persist(db, source, old, other, new, cycle="refresh")
    assert "recheck_selected" in refreshed["material_decisions"].values()
    check = db.take()
    finish(db, source, check, "Corrected source evidence with a substantive update. " * 8)
    following = persist(db, source, old, other, new, cycle="next")
    assert "new_material_selected" in following["material_decisions"].values()
    assert "material_quota_deferred" in following["material_decisions"].values()
    new_task = db.take()
    with db.scope() as session:
        task = session.get(PipelineTask, new_task.task_id)
        assert task and task.article_id != check.article_id


def test_changed_identity_refreshes_but_unchanged_body_reuses_paid_task(
    ingestion_db: IngestionDB,
) -> None:
    db = ingestion_db
    source, item = quota_source(db), db.item("same")
    persist(db, source, item, cycle="first")
    first = db.take()
    body = "Evidence from the same independently identified source. " * 8
    paid = finish(db, source, first, body)["card_task_id"]
    with db.scope() as session:
        row = session.get(PipelineTask, first.task_id)
        assert row
        row.created_at = datetime.now(UTC) - timedelta(days=2)
    persist(db, source, item, cycle="periodic")
    refreshed = db.take()
    assert finish(db, source, refreshed, body)["card_task_id"] == paid
    changed = item.model_copy(update={"title": "Corrected headline"})
    persist(db, source, changed, cycle="correction")
    correction = db.take()
    assert finish(db, source, correction, body)["card_task_id"] != paid
    with db.scope() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(PipelineTask).where(PipelineTask.queue == "paid")
            )
            == 2
        )


def test_material_and_paid_caps_are_independent_and_backlog_needs_no_refetch(
    ingestion_db: IngestionDB,
) -> None:
    db = ingestion_db
    source = quota_source(db, material=3, paid=1)
    items = tuple(db.item(str(i)) for i in range(3))
    persist(db, source, *items, cycle="first")
    outputs = [
        finish(db, source, db.take(), f"Independent observed text number {i}. " * 8)
        for i in range(3)
    ]
    assert sum("card_task_id" in out for out in outputs) == 1
    assert sum(out["card_enqueue_reason"] == "paid_quota_deferred" for out in outputs) == 2
    with db.scope() as session:
        paid = session.scalar(select(PipelineTask).where(PipelineTask.queue == "paid"))
        assert paid
        paid.status, paid.due_at = "budget_deferred", datetime.now(UTC) + timedelta(days=1)
    out = persist(db, source, *items, cycle="next")
    assert out["material_selected"] == 0
    with db.scope() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(PipelineTask)
                .where(PipelineTask.queue == "material")
            )
            == 3
        )
        assert (
            session.scalar(
                select(func.count()).select_from(PipelineTask).where(PipelineTask.queue == "paid")
            )
            == 2
        )
        batch = session.get(DiscoveryBatch, out["batch_id"])
        assert batch
        reasons = [value["reason"] for value in batch.paid_outcomes.values()]
        assert sorted(reasons) == ["paid_quota_deferred", "paid_reused", "paid_selected"]


def test_slow_material_retry_and_new_polls_keep_one_allocation(ingestion_db: IngestionDB) -> None:
    db, source = ingestion_db, quota_source(ingestion_db)
    old, new = db.item("slow"), db.item("new")
    persist(db, source, old, cycle="first")
    slow = db.take()
    with db.scope() as session:
        assert fail(session, slow, error="mock timeout")
    out = persist(db, source, old, new, cycle="poll")
    assert out["material_selected"] == 1
    assert "material_inflight_reused" in out["material_decisions"].values()
    with db.scope() as session:
        assert session.scalar(select(func.count()).select_from(PipelineTask)) == 2
        task = session.get(PipelineTask, slow.task_id)
        assert task and task.status == "retry_wait" and task.failures == 1


def test_concurrent_completion_restart_and_rollback_do_not_reallocate(
    ingestion_db: IngestionDB,
) -> None:
    db, source = ingestion_db, quota_source(ingestion_db)
    item, barrier = db.item(), threading.Barrier(2)

    def run() -> dict[str, Any]:
        barrier.wait(timeout=5)
        return persist(db, source, item, db.item("later"), cycle="same-schedule")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result(timeout=10) for future in [pool.submit(run), pool.submit(run)]]
    assert sorted(result["replayed"] for result in results) == [False, True]
    assert len({result["batch_id"] for result in results}) == 1
    with pytest.raises(RuntimeError, match="transaction interrupted"), db.scope() as session:
        persist_discovery(
            session,
            source,
            DiscoveryResult(
                source_id=source.id,
                observed_at=datetime.now(UTC),
                response_fingerprint="new",
                items=(db.item("rollback"),),
            ),
            cycle="rollback",
        )
        raise RuntimeError("transaction interrupted")
    out = persist(db, source, db.item("rollback"), cycle="rollback")
    assert out["material_selected"] == 1 and not out["replayed"]


def test_canonical_reprint_keeps_provenance_without_another_paid_slot(
    ingestion_db: IngestionDB,
) -> None:
    db, source = ingestion_db, quota_source(ingestion_db, material=2, paid=2)
    persist(db, source, db.item("original"), db.item("reprint"), cycle="first")
    body = "Identical attributable body with enough source context. " * 8
    first = finish(db, source, db.take(), body)
    duplicate = finish(db, source, db.take(), body)
    assert "card_task_id" in first
    assert duplicate["card_enqueue_reason"] == "canonical_duplicate"
    assert "card_task_id" not in duplicate


def test_unknown_time_is_retained_and_only_supported_old_reports_are_skipped(
    ingestion_db: IngestionDB,
) -> None:
    db, source = ingestion_db, quota_source(ingestion_db)
    old = ContentTime(
        kind="original",
        precision="time",
        at=datetime.now(UTC) - timedelta(days=40),
        basis="synthetic:original",
    )
    stale = db.item("stale", metadata=ContentMetadata(form="article", genre="news", times=(old,)))
    unknown = db.item("unknown")
    out = persist(db, source, stale, unknown, cycle="first")
    assert sorted(out["material_decisions"].values()) == ["new_material_selected", "stale_report"]
    assert out["new_candidates"] == 2


def test_concurrent_material_results_share_the_same_paid_cap(ingestion_db: IngestionDB) -> None:
    db, source = ingestion_db, quota_source(ingestion_db, material=2, paid=1)
    persist(db, source, db.item("one"), db.item("two"), cycle="first")
    leases, barrier = [db.take(), db.take()], threading.Barrier(2)

    def run(index: int) -> dict[str, Any]:
        barrier.wait(timeout=5)
        return finish(db, source, leases[index], f"Different source evidence number {index}. " * 8)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, i) for i in range(2)]
        results = [future.result(timeout=10) for future in futures]
    assert sum("card_task_id" in value for value in results) == 1
    with db.scope() as session:
        batch = session.scalar(select(DiscoveryBatch))
        assert batch and batch.counters["paid_counts"] == {
            "paid_selected": 1,
            "paid_quota_deferred": 1,
        }


def test_page_enrichment_does_not_force_an_early_material_recheck(
    ingestion_db: IngestionDB,
) -> None:
    from unspun.core.models import Article

    db, source = ingestion_db, quota_source(ingestion_db)
    item = db.item()
    persist(db, source, item, cycle="first")
    lease = db.take()
    finish(db, source, lease, "Actual body with independent evidence and attribution. " * 8)
    with db.scope() as session:
        article = session.get(Article, lease.article_id)
        assert article and article.r1_metadata
        article.r1_metadata = {
            **article.r1_metadata,
            "times": [
                {
                    "kind": "original",
                    "precision": "time",
                    "at": datetime.now(UTC).isoformat(),
                    "basis": "page:verified-publication",
                }
            ],
        }
    out = persist(db, source, item, cycle="next")
    assert out["material_selected"] == 0
    assert list(out["material_decisions"].values()) == ["recheck_not_due"]


def test_zero_quotas_keep_only_metadata_without_spending_slots(ingestion_db: IngestionDB) -> None:
    db, source = ingestion_db, quota_source(ingestion_db, material=0, paid=0)
    out = persist(db, source, db.item(), cycle="first")
    assert out["new_candidates"] == 1 and out["material_selected"] == 0
    with db.scope() as session:
        assert session.scalar(select(func.count()).select_from(PipelineTask)) == 0


@pytest.mark.parametrize(
    "field,value",
    [("scan", 0), ("scan", 201), ("paid", -1), ("material", 201), ("recheck_seconds", 0)],
)
def test_quotas_require_explicit_bounds(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        DiscoveryQuotas.model_validate({"scan": 30, "material": 1, "paid": 1, field: value})


@pytest.mark.parametrize(
    "adapter", ["rss", "zhihu_daily", "people_daily", "thepaper", "netease", "tencent"]
)
def test_every_adapter_reports_pre_and_post_scan_counts_without_extra_requests(
    adapter: str,
) -> None:
    requests: list[str] = []
    sources = {source.id: source for source in load_sources()}
    source_id = {
        "rss": "bbc-zhongwen",
        "zhihu_daily": "zhihu-daily",
        "people_daily": "people-frontpage",
        "thepaper": "thepaper-sidebar",
        "netease": "netease-home",
        "tencent": "tencent-headlines",
    }[adapter]
    raw = sources[source_id].model_dump(mode="json")
    raw["max_items"] = 1
    raw["r1"]["quotas"] = {"scan": 3, "material": 1, "paid": 1}
    source = Source.model_validate(raw)
    identities = ["1", "1", "2", "3"]

    def response(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if adapter == "rss":
            xml = (
                "<rss><channel>"
                + "".join(
                    f"<item><guid>{i}</guid><title>Item {i}</title><link>https://example.org/{i}</link></item>"
                    for i in identities
                )
                + "</channel></rss>"
            )
            return httpx.Response(200, text=xml)
        if adapter == "zhihu_daily":
            return httpx.Response(
                200,
                json={
                    "date": "20261019",
                    "stories": [{"id": i, "title": "Item " + i} for i in identities],
                },
            )
        if adapter == "people_daily":
            if request.url.path.endswith("index.html"):
                return httpx.Response(200, text='<a href="202610/19/node_01.html">Front</a>')
            return httpx.Response(
                200,
                text="".join(
                    f'<a href="/rmrb/pc/content/202610/19/content_{i}.html">Item {i}</a>'
                    for i in identities
                ),
            )
        if adapter == "netease":
            return httpx.Response(
                200,
                text='<div id="js_top_news">'
                + "".join(
                    f'<a href="https://www.163.com/news/article/L9EQ37VT000189F{i}.html">'
                    f"Item {i}</a>"
                    for i in identities
                )
                + "</div>",
            )
        if adapter == "thepaper":
            return httpx.Response(
                200,
                json={
                    "resultCode": 1,
                    "data": {
                        "hotNews": [
                            {"contId": i, "name": "Item " + i, "contType": 0} for i in identities
                        ]
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": [
                    {
                        "article_list": [
                            {
                                "id": "20261019V03N7T0" + i,
                                "title": "Item " + i,
                                "url": "https://news.qq.com/rain/a/20261019V03N7T0" + i,
                            }
                            for i in identities
                        ]
                    }
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        result = discover(source, client, now=datetime(2026, 10, 19, tzinfo=UTC))
    assert result.scan_counts == {
        "listed": 4,
        "scanned": 3,
        "valid": 3,
        "adapter_duplicates": 0 if adapter == "rss" else 1,
    }
    assert len({item.identity_value for item in result.items}) == 2
    assert len(requests) == (2 if adapter == "people_daily" else 1)
    raw["r1"]["quotas"] = None
    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        legacy = discover(
            Source.model_validate(raw), client, now=datetime(2026, 10, 19, tzinfo=UTC)
        )
    assert len(legacy.items) == 1 and legacy.scan_counts is None
    assert len(result.items) > len(legacy.items)
