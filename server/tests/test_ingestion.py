"""Metadata-first ingestion, material boundaries, and exact identities in real PG."""

import gzip
import os
import threading
import uuid
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from pydantic import HttpUrl, ValidationError
from sqlalchemy import create_engine, delete, func, select, update
from sqlalchemy.orm import Session

from unspun.core.config import get_settings
from unspun.core.content import ContentMetadata, ContentTime, Paragraph, fingerprint
from unspun.core.html_text import visible_text
from unspun.core.models import (
    Article,
    ContentDerivation,
    ContentIdentity,
    ContentMaterial,
    ContentObservation,
    ContentUrl,
)
from unspun.core.sources import Source, load_sources
from unspun.core.task_models import DiscoveryBatch, PipelineTask, SourceState, TaskAttempt
from unspun.core.tasks import Lease, claim, complete
from unspun.pipeline.discovery import (
    DiscoveryItem,
    DiscoveryResult,
    discover,
    persist_discovery,
    public_url,
)
from unspun.pipeline.materials import MaterialResult, apply_material, retrieve_material
from unspun.pipeline.r1_worker import SessionScope

NOW = datetime(2026, 10, 16, 8, tzinfo=UTC)


@dataclass
class IngestionDB:
    prefix: str
    scope: SessionScope

    def source(self, name: str = "one", **config: Any) -> Source:
        return Source.model_validate(
            {
                "id": self.prefix + name,
                "name": "Synthetic",
                "url": "https://example.org/feed",
                "weight": 0.5,
                "region": "intl",
                "kind": "commercial",
                "lang": "en",
                "legacy_enabled": False,
                "discovery_owner": "r1",
                "r1": {
                    "discovery": True,
                    "material": True,
                    "origin_hosts": ["example.org"],
                    **config,
                },
            }
        )

    def item(self, name: str = "one", **values: Any) -> DiscoveryItem:
        return DiscoveryItem(
            url=HttpUrl(f"https://example.org/{self.prefix}/{name}"),
            title=values.pop("title", "Synthetic title"),
            item_key=name,
            identity_namespace=self.prefix,
            identity_value=name,
            metadata=values.pop("metadata", ContentMetadata(form="article")),
            **values,
        )

    def persist(
        self, source: Source, *items: DiscoveryItem, cycle: str = "one", now: datetime = NOW
    ) -> dict[str, Any]:
        with self.scope() as session:
            return persist_discovery(
                session,
                source,
                DiscoveryResult(
                    source_id=source.id,
                    observed_at=now,
                    response_fingerprint=fingerprint(cycle),
                    items=items,
                ),
                cycle=cycle,
            )

    def take(self) -> Lease:
        with self.scope() as session:
            lease = claim(session, queue="material", kinds={"fetch_material"}, worker=self.prefix)
            assert lease
            return lease

    def finish(self, lease: Lease, result: MaterialResult) -> None:
        with self.scope() as session:
            assert complete(session, lease, apply=lambda db: apply_material(db, lease, result))


@pytest.fixture
def ingestion_db(db_session: Session) -> Generator[IngestionDB]:
    assert os.environ.get("UNSPUN_DATABASE_URL"), "an explicit migrated isolated DB is required"
    engine = create_engine(get_settings().database_url, pool_size=8)
    prefix = "synthetic-ingestion-" + uuid.uuid4().hex

    @contextmanager
    def scope() -> Generator[Session]:
        with Session(engine) as session, session.begin():
            yield session

    yield IngestionDB(prefix, scope)
    with scope() as session:
        session.execute(delete(DiscoveryBatch).where(DiscoveryBatch.source_id.startswith(prefix)))
        ids = list(session.scalars(select(Article.id).where(Article.source_id.startswith(prefix))))
        task_ids = select(PipelineTask.id).where(
            PipelineTask.article_id.in_(ids) | PipelineTask.source_id.startswith(prefix)
        )
        session.execute(delete(TaskAttempt).where(TaskAttempt.task_id.in_(task_ids)))
        session.execute(
            delete(PipelineTask).where(
                PipelineTask.article_id.in_(ids) | PipelineTask.source_id.startswith(prefix)
            )
        )
        session.execute(
            update(Article)
            .where(Article.id.in_(ids))
            .values(current_material_id=None, canonical_content_id=None)
        )
        for model in (
            ContentDerivation,
            ContentObservation,
            ContentIdentity,
            ContentUrl,
            ContentMaterial,
        ):
            session.execute(delete(model).where(model.article_id.in_(ids)))
        session.execute(delete(Article).where(Article.id.in_(ids)))
        session.execute(delete(SourceState).where(SourceState.source_id.startswith(prefix)))
    engine.dispose()


def material(
    lease: Lease, body: str = "A self-contained observed text unit. " * 8, **values: Any
) -> MaterialResult:
    raw = dict(lease.payload["metadata"])
    title = raw.pop("title")
    return MaterialResult(
        scope=values.pop("scope", "open_text_unit"),
        access_status=values.pop("access_status", "ok"),
        completeness="observed_unit" if body else "none",
        basis="synthetic",
        source_url=lease.payload["url"],
        retrieved_at=NOW,
        paragraphs=(Paragraph(text=body),) if body else (),
        metadata=ContentMetadata.model_validate(raw),
        title=title,
        **values,
    )


def test_metadata_commits_before_material_and_leaves_legacy_fields_empty(
    ingestion_db: IngestionDB,
) -> None:
    source, item = ingestion_db.source(), ingestion_db.item(provided_text="Feed lead")
    assert ingestion_db.persist(source, item)["new_candidates"] == 1
    lease = ingestion_db.take()
    with ingestion_db.scope() as session:
        row = session.get(Article, lease.article_id)
        assert row and row.processing_track == "r1" and row.event_id is None
        assert row.current_material_id is None and row.content is None and row.summary_zh is None
        assert session.scalar(select(func.count()).select_from(ContentObservation)) == 1
    failed = material(lease, "", scope="none", access_status="restricted")
    ingestion_db.finish(lease, failed)
    with ingestion_db.scope() as session:
        row = session.get(Article, lease.article_id)
        assert row and row.current_material_id
        assert session.get(ContentMaterial, row.current_material_id).access_status == "restricted"  # type: ignore[union-attr]


def test_same_url_keeps_routes_but_one_r1_object_and_successor(ingestion_db: IngestionDB) -> None:
    first, second = ingestion_db.source("a"), ingestion_db.source("b")
    item = ingestion_db.item()
    assert ingestion_db.persist(first, item)["new_candidates"] == 1
    assert ingestion_db.persist(first, item)["new_candidates"] == 0
    assert (
        ingestion_db.persist(second, item.model_copy(update={"title": "Alternate channel title"}))[
            "new_candidates"
        ]
        == 0
    )
    with ingestion_db.scope() as session:
        rows = list(session.scalars(select(Article)))
        assert len(rows) == 1 and rows[0].title == item.title
        assert session.scalar(select(func.count()).select_from(ContentObservation)) == 2
        tasks = list(session.scalars(select(PipelineTask)))
        assert len(tasks) == 2  # one per independently observed channel, no retry duplicates
        assert len({row.object_key for row in tasks}) == 1
        assert all(row.queue == "material" for row in tasks)


def test_existing_legacy_url_and_history_are_not_taken_over(
    ingestion_db: IngestionDB, db_session: Session
) -> None:
    item = ingestion_db.item()
    historical = Article(
        source_id="legacy-synthetic",
        title="Historical",
        url=str(item.url),
        content="Historical material",
        summary_zh="Historical summary",
        processing_track="legacy",
    )
    db_session.add(historical)
    db_session.flush()
    assert ingestion_db.persist(ingestion_db.source(), item)["new_candidates"] == 1
    db_session.refresh(historical)
    assert historical.title == "Historical" and historical.content == "Historical material"
    assert historical.processing_track == "legacy" and historical.summary_zh == "Historical summary"
    assert (
        db_session.scalar(
            select(func.count()).select_from(Article).where(Article.url == str(item.url))
        )
        == 2
    )


def test_platform_identity_retains_url_alias_and_refuses_conflict(
    ingestion_db: IngestionDB,
) -> None:
    source, first = ingestion_db.source(), ingestion_db.item()
    ingestion_db.persist(source, first)
    alias = first.model_copy(update={"url": HttpUrl(str(first.url) + "?edition=2")})
    assert ingestion_db.persist(source, alias, cycle="two")["new_candidates"] == 0
    another = ingestion_db.item("other")
    ingestion_db.persist(source, another)
    conflict = first.model_copy(update={"url": another.url})
    with pytest.raises(ValueError, match="conflict"):
        ingestion_db.persist(source, conflict, cycle="conflict")
    with ingestion_db.scope() as session:
        assert session.scalar(select(func.count()).select_from(ContentUrl)) == 3


def seed_ready(session: Session, row: Article) -> None:
    assert row.current_material_id
    session.add(
        ContentDerivation(
            article_id=row.id,
            material_id=row.current_material_id,
            kind="card",
            status="ready",
            input_fingerprint=uuid.uuid4().hex,
            metadata_fingerprint=row.metadata_fingerprint or "test",
            contract_version="synthetic",
            review_contract="synthetic",
            payload={},
            review_evidence={},
        )
    )


def test_material_and_metadata_versions_invalidate_ready_outputs(ingestion_db: IngestionDB) -> None:
    source, item = ingestion_db.source(), ingestion_db.item()
    ingestion_db.persist(source, item)
    lease = ingestion_db.take()
    ingestion_db.finish(lease, material(lease))
    with ingestion_db.scope() as session:
        row = session.get(Article, lease.article_id)
        assert row
        original = row.current_material_id
        seed_ready(session, row)
    ingestion_db.persist(source, item.model_copy(update={"title": "Corrected title"}), cycle="two")
    with ingestion_db.scope() as session:
        assert session.scalar(select(ContentDerivation.status)) == "invalidated"
    changed = ingestion_db.take()
    ingestion_db.finish(changed, material(changed, "Updated evidence. " * 10))
    with ingestion_db.scope() as session:
        row = session.get(Article, lease.article_id)
        assert row and row.current_material_id != original and row.title == "Corrected title"
        assert session.scalar(select(func.count()).select_from(ContentMaterial)) == 2
        assert session.get(ContentMaterial, original) is not None


def test_concurrent_exact_bodies_have_one_root_and_overlap_is_not_merged(
    ingestion_db: IngestionDB,
) -> None:
    source = ingestion_db.source()
    ingestion_db.persist(
        source, ingestion_db.item("a"), ingestion_db.item("b"), ingestion_db.item("overlap")
    )
    first, second, overlap = ingestion_db.take(), ingestion_db.take(), ingestion_db.take()
    barrier = threading.Barrier(2)

    def finish(lease: Lease) -> None:
        barrier.wait(timeout=5)
        ingestion_db.finish(lease, material(lease))

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(finish, lease) for lease in (first, second)]
        for future in futures:
            future.result(timeout=10)
    ingestion_db.finish(
        overlap,
        material(
            overlap,
            "A self-contained observed text unit. " * 6
            + "An independently valuable partial overlap.",
        ),
    )
    with ingestion_db.scope() as session:
        rows = list(session.scalars(select(Article).order_by(Article.id)))
        roots = [row for row in rows if row.canonical_content_id is None]
        assert len(roots) == 2
        assert (
            next(row for row in rows if row.id == overlap.article_id).canonical_content_id is None
        )
        duplicate = next(row for row in rows if row.canonical_content_id is not None)
        assert duplicate.canonical_content_id in {first.article_id, second.article_id}


def test_changed_root_detaches_old_exact_alias_without_losing_its_body(
    ingestion_db: IngestionDB,
) -> None:
    source = ingestion_db.source()
    ingestion_db.persist(source, ingestion_db.item("a"), ingestion_db.item("b"))
    first, second = ingestion_db.take(), ingestion_db.take()
    ingestion_db.finish(first, material(first))
    ingestion_db.finish(second, material(second))
    with ingestion_db.scope() as session:
        alias = session.get(Article, second.article_id)
        assert alias and alias.canonical_content_id == first.article_id
        seed_ready(session, alias)
        alias_material = alias.current_material_id
        apply_material(
            session, first, material(first, "A genuinely different corrected material. " * 10)
        )
    with ingestion_db.scope() as session:
        alias = session.get(Article, second.article_id)
        assert (
            alias
            and alias.canonical_content_id is None
            and alias.current_material_id == alias_material
        )
        assert session.scalar(select(ContentDerivation.status)) == "invalidated"


def test_repeated_material_result_reuses_version(ingestion_db: IngestionDB) -> None:
    ingestion_db.persist(ingestion_db.source(), ingestion_db.item())
    lease = ingestion_db.take()
    result = material(lease)
    ingestion_db.finish(lease, result)
    with ingestion_db.scope() as session:
        first = apply_material(session, lease, result)
        second = apply_material(session, lease, result)
        assert first == second
        assert session.scalar(select(func.count()).select_from(ContentMaterial)) == 1


@pytest.mark.parametrize(
    "scope,form",
    [
        ("complete_brief", "post"),
        ("preview", "article"),
        ("question_background", "question"),
        ("media_description", "video"),
    ],
)
def test_feed_units_keep_actual_scope_without_pretending_to_fetch_origin(
    ingestion_db: IngestionDB, scope: str, form: str
) -> None:
    source = ingestion_db.source(material_scope=scope, form=form)
    raw = ContentMetadata(form=form).model_dump(mode="json")  # type: ignore[arg-type]
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: pytest.fail("declared feed unit needs no origin request")
        )
    ) as client:
        result = retrieve_material(
            source,
            {
                "url": "https://example.org/item",
                "metadata": {"title": "Unit", **raw},
                "provided_text": "An actual supplied unit.",
            },
            client,
            now=NOW,
        )
    assert result.scope == scope and result.metadata.form == form
    assert (
        result.response_status is None and result.paragraphs[0].text == "An actual supplied unit."
    )
    assert result.completeness == ("observed_unit" if scope == "complete_brief" else "partial")


@pytest.mark.parametrize("scope", ["preview", "open_text_unit"])
def test_material_retention_does_not_expand_the_paid_scope(
    ingestion_db: IngestionDB, scope: str
) -> None:
    from unspun.pipeline.materials import MaterialHandler

    source = ingestion_db.source(paid=True, paid_scopes=["preview"])
    ingestion_db.persist(source, ingestion_db.item())
    lease = ingestion_db.take()
    handler = MaterialHandler({source.id: source})
    with ingestion_db.scope() as session:
        assert complete(
            session,
            lease,
            apply=lambda db: handler.apply(db, lease, material(lease, "Actual unit.", scope=scope)),
        )
    with ingestion_db.scope() as session:
        article = session.get(Article, lease.article_id)
        assert article and article.current_material_id
        current = session.get(ContentMaterial, article.current_material_id)
        assert current and current.scope == scope
        cards = list(session.scalars(select(PipelineTask).where(PipelineTask.queue == "paid")))
        assert len(cards) == (1 if scope == "preview" else 0)


@pytest.mark.parametrize("status", [401, 403, 429, 503])
def test_origin_failure_preserves_feed_lead_and_access_result(
    ingestion_db: IngestionDB, status: int
) -> None:
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(status))) as client:
        result = retrieve_material(
            ingestion_db.source(),
            {
                "url": "https://example.org/item",
                "metadata": {"title": "Item"},
                "provided_text": "Observed lead",
            },
            client,
            now=NOW,
        )
    assert result.scope == "feed_lead" and result.completeness == "partial"
    assert result.access_status == ("restricted" if status in {401, 403, 429} else "unavailable")
    assert result.response_status == status and result.paragraphs[0].text == "Observed lead"


def test_gzip_hidden_text_and_verified_xinhua_metadata(ingestion_db: IngestionDB) -> None:
    html = (
        '<meta name="publishdate" content="2026-10-15">'
        '<meta name="source" content="\u65b0\u534e\u7f51">'
        '<meta property="article:published_time" content="2026-10-16T01:00:00Z">'
        '<span id="detailContent">'
        "<p>\u65b0\u534e\u793e\u5317\u4eac10\u670815\u65e5\u7535\uff08\u8bb0\u8005"
        "\u5b59\u840d\uff09A fact.</p>"
        "<p hidden>Hidden false fact.</p>"
        "<script>Bad script</script>"
        "<p>Visible ending.</p>"
        "<p>Visible ending.</p>"
        "</span>"
    )
    source = ingestion_db.source(origin_hosts=["news.cn"])
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"content-encoding": "gzip", "content-type": "text/html; charset=utf-8"},
                content=gzip.compress(html.encode()),
            )
        )
    ) as client:
        result = retrieve_material(
            source,
            {"url": "https://www.news.cn/item", "metadata": {"title": "Item"}},
            client,
            now=NOW,
        )
    assert result.scope == "open_text_unit" and result.basis == "xinhua:#detailContent"
    assert len(result.paragraphs) == 2 and "Hidden" not in str(result.paragraphs)
    assert result.metadata.authors[0].role == "reporter"
    original = next(value for value in result.metadata.times if value.kind == "original")
    assert original.precision == "date" and original.on and original.on.isoformat() == "2026-10-15"
    assert original.at is None


def test_xinhua_media_url_is_evidence_of_description_not_video_content(
    ingestion_db: IngestionDB,
) -> None:
    html = (
        '<span video_src="https://media.example.org/clip.mp4">'
        "</span>"
        '<div id="detailContent">'
        "<p>A description of the public clip.</p>"
        "</div>"
    )
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=html))
    ) as client:
        result = retrieve_material(
            ingestion_db.source(origin_hosts=["news.cn"]),
            {"url": "https://www.news.cn/item", "metadata": {"title": "Clip"}},
            client,
            now=NOW,
        )
    assert (
        result.metadata.form == "video"
        and str(result.metadata.media_url) == "https://media.example.org/clip.mp4"
    )
    assert result.scope == "media_description" and result.completeness == "partial"
    assert result.metadata.duration_seconds is None


def test_verified_cctv_footer_is_retained_as_credits_not_paid_duplicate_body(
    ingestion_db: IngestionDB,
) -> None:
    from unspun.pipeline.materials import _clean_body  # pyright: ignore[reportPrivateUsage]

    body = "An observed shared article.\nA substantive ending."
    footer = (
        "\u603b\u76d1\u5236\u4e28Editorial Credits\n\xa92026\u4e2d"
        "\u592e\u5e7f\u64ad\u7535\u89c6\u603b\u53f0\u7248\u6743\u6240\u6709\u3002"
        "\u672a\u7ecf\u8bb8\u53ef\uff0c\u8bf7\u52ff\u8f6c\u8f7d\u4f7f\u7528\u3002"
    )
    clean, credits = _clean_body(body + "\n" + footer, "https://news.qq.com/rain/a/1")
    assert "\n".join(clean) == body and credits
    unchanged, removed = _clean_body(body + "\n" + footer, "https://unverified.example.org/item")
    assert len(unchanged) == 4 and not removed


def test_redirect_to_internal_network_never_gets_a_request(ingestion_db: IngestionDB) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1:5432/private"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = retrieve_material(
            ingestion_db.source(),
            {"url": "https://example.org/item", "metadata": {"title": "Item"}},
            client,
            now=NOW,
        )
    assert seen == ["https://example.org/item"]
    assert result.scope == "none" and result.access_status == "failed"


def test_challenge_and_missing_known_container_do_not_become_fulltext(
    ingestion_db: IngestionDB,
) -> None:
    for html in (
        "<body>Navigation only</body>",
        '<div id="detailContent">Verify you are human captcha</div>',
    ):
        with httpx.Client(
            transport=httpx.MockTransport(lambda _, html=html: httpx.Response(200, text=html))
        ) as client:
            result = retrieve_material(
                ingestion_db.source(origin_hosts=["news.cn"]),
                {"url": "https://www.news.cn/item", "metadata": {"title": "Item"}},
                client,
                now=NOW,
            )
        assert result.scope == "none" and not result.paragraphs
        assert result.access_status != "ok"


@pytest.mark.parametrize("provided", [None, "An actually observed RSS introduction."])
def test_douban_security_redirect_cannot_publish_its_logo_or_template_metadata(
    ingestion_db: IngestionDB, provided: str | None
) -> None:
    source = ingestion_db.source(origin_hosts=["movie.douban.com", "sec.douban.com"])
    seen: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.host == "movie.douban.com":
            return httpx.Response(302, headers={"Location": "https://sec.douban.com/c?r=review"})
        return httpx.Response(
            200,
            text=(
                '<meta name="author" content="Security template author">'
                '<meta property="article:published_time" content="2026-10-16T10:00:00Z">'
                "<article>d o u b a n</article>"
            ),
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = retrieve_material(
            source,
            {
                "url": "https://movie.douban.com/review/123/",
                "metadata": {"title": "Synthetic review", "genre": "review"},
                "provided_text": provided,
            },
            client,
            now=NOW,
        )
    assert len(seen) == 2 and result.response_status == 200
    assert result.access_status == "restricted" and result.evidence["security_redirect"] is True
    assert result.metadata.authors == result.metadata.times == ()
    assert [p.text for p in result.paragraphs] == ([provided] if provided else [])
    assert result.scope == ("feed_lead" if provided else "none")
    assert result.completeness == ("partial" if provided else "none")


@pytest.mark.parametrize(
    "schema,url,expected",
    [
        ('{"@type":"VideoObject","name":"Synthetic clip"}', "/news/videos/item", "video"),
        ('{"@type":"VideoObject","name":"Synthetic clip"}', "/untyped-item", "video"),
        ('{"@type":"NewsArticle","name":"Synthetic article"}', "/news/videos/item", "article"),
    ],
)
def test_bbc_primary_schema_sets_description_scope_without_inferring_viewed_video(
    ingestion_db: IngestionDB, schema: str, url: str, expected: str
) -> None:
    source = ingestion_db.source(origin_hosts=["bbc.co.uk"])
    html = (
        '<html><head><script type="application/ld+json">'
        + schema
        + "</script></head><body><article><p>A written description with an attributed source "
        "statement. This public text accompanies the clip, without a transcript or timing. "
        "The source describes the announcement and explains the context in this passage. "
        "The available text provides background while the moving images remain separate."
        "</p></article></body></html>"
    )
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=html))
    ) as client:
        result = retrieve_material(
            source,
            {
                "url": "https://www.bbc.co.uk" + url,
                "metadata": {"title": "Synthetic clip", "form": "article"},
            },
            client,
            now=NOW,
        )
    assert result.metadata.form == expected
    assert result.scope == ("media_description" if expected == "video" else "open_text_unit")
    assert result.metadata.duration_seconds is None and result.metadata.media_url is None


@pytest.mark.parametrize(
    "description",
    [
        None,
        "An actual description of the source material.",
        "\u8bb0\u8005\uff1a\u8bf7\u4ecb\u7ecd\u4e00\u4e0b\u672c\u6b21\u4f1a\u8bae\u7684\u4e3b\u8981\u5185\u5bb9\uff1f",
    ],
)
def test_xinhua_media_credits_alone_are_not_reading_material(
    ingestion_db: IngestionDB, description: str | None
) -> None:
    source = ingestion_db.source(origin_hosts=["news.cn"], platform="xinhua")
    intro = f"<p>{description}</p>" if description else ""
    html = (
        '<span video_src="https://media.example.org/clip.mp4"></span>'
        '<div id="detailContent">' + intro + "<p>\u8bb0\u8005\uff1a\u738b\u96e8\u8427</p>"
        "<p>\u7f16\u5bfc\uff1a\u5510\u5b50\u6654</p>"
        "<p>\u65b0\u534e\u793e\u97f3\u89c6\u9891\u90e8\u5236\u4f5c</p></div>"
    )
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=html))
    ) as client:
        result = retrieve_material(
            source,
            {
                "url": "https://www.news.cn/item",
                "metadata": {"title": "Synthetic video", "platform": "xinhua"},
            },
            client,
            now=NOW,
        )
    assert result.metadata.form == "video"
    assert result.scope == ("media_description" if description else "none")
    assert bool(result.paragraphs) is bool(description)
    assert bool(result.evidence.get("media_credits_only")) is not bool(description)


def test_rss_metadata_keeps_feed_date_and_modified_time_distinct(ingestion_db: IngestionDB) -> None:
    xml = (
        b'<feed xmlns="http://www.w3.org/2005/Atom">'
        b"<entry>"
        b"<id>one</id>"
        b'<link href="https://example.org/item?utm_source=test"/>'
        b"<title>Actual title</title>"
        b"<published>2024-03-02</published>"
        b"<updated>2026-10-16T07:00:00Z</updated>"
        b"<author>"
        b"<name>Actual Author</name>"
        b"</author>"
        b'<content type="html">&lt;p&gt;A feed unit&lt;/p&gt;</content>'
        b"</entry>"
        b"</feed>"
    )
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=xml))
    ) as client:
        result = discover(ingestion_db.source(), client, now=NOW)
    item = result.items[0]
    assert str(item.url) == "https://example.org/item"
    assert item.metadata.times[0].kind == "feed" and item.metadata.times[0].precision == "date"
    assert item.metadata.times[0].on and item.metadata.times[0].on.year == 2024
    assert item.metadata.times[1].kind == "modified" and item.metadata.times[1].at
    assert all(value.kind != "original" for value in item.metadata.times)
    assert (
        item.metadata.authors[0].name == "Actual Author"
        and item.metadata.authors[0].role == "unknown"
    )
    assert item.signals is None and item.rank is None


def test_source_contract_keeps_existing_configuration_and_single_owner() -> None:
    assert load_sources() and all(
        not source.r1
        or not source.r1.publish
        or (source.discovery_owner == "r1" and not source.legacy_enabled)
        for source in load_sources()
    )
    raw = {
        "id": "synthetic",
        "name": "Test",
        "url": "https://example.org/feed",
        "weight": 0.5,
        "region": "intl",
        "kind": "commercial",
        "lang": "en",
    }
    assert Source.model_validate(raw).legacy_enabled
    with pytest.raises(ValidationError):
        Source.model_validate({**raw, "r1": {"discovery": True}})
    with pytest.raises(ValidationError):
        Source.model_validate({**raw, "discovery_owner": "r1"})
    with pytest.raises(ValueError):
        public_url("http://127.0.0.1:1200/internal")
    assert (
        visible_text('<p>Safe</p><div style="display: none">False</div><script>False</script>')
        == "Safe"
    )


def test_transient_lesser_material_does_not_erase_last_observed_unit(
    ingestion_db: IngestionDB,
) -> None:
    ingestion_db.persist(ingestion_db.source(), ingestion_db.item())
    lease = ingestion_db.take()
    original = material(lease)
    ingestion_db.finish(lease, original)
    with ingestion_db.scope() as session:
        row = session.get(Article, lease.article_id)
        assert row
        original_id = row.current_material_id
        failed = material(lease, "Observed lead", scope="feed_lead", access_status="restricted")
        output = apply_material(session, lease, failed)
        assert output["retained_previous_material"] is True
        assert row.current_material_id == original_id
        assert session.scalar(select(func.count()).select_from(ContentMaterial)) == 2


def test_time_observation_does_not_refresh_old_original_or_duplicate_version(
    ingestion_db: IngestionDB,
) -> None:
    old = ContentTime(
        kind="original", precision="time", at=NOW - timedelta(days=400), basis="synthetic:original"
    )
    ingestion_db.persist(
        ingestion_db.source(),
        ingestion_db.item(metadata=ContentMetadata(form="article", times=(old,))),
    )
    lease = ingestion_db.take()
    first = material(lease)
    ingestion_db.finish(lease, first)
    with ingestion_db.scope() as session:
        apply_material(
            session, lease, first.model_copy(update={"retrieved_at": NOW + timedelta(days=30)})
        )
        row = session.get(Article, lease.article_id)
        assert row and row.r1_metadata
        assert row.r1_metadata["times"][0]["at"] == old.model_dump(mode="json")["at"]
        assert session.scalar(select(func.count()).select_from(ContentMaterial)) == 1


def test_body_identity_normalizes_chinese_wrapping_but_keeps_word_boundaries() -> None:
    from unspun.pipeline.materials import body_identity

    assert body_identity("\u4e2d\u6587\n\u5185\u5bb9\u3002\n\u7ed3\u5c3e") == body_identity(
        "\u4e2d\u6587\u5185\u5bb9\u3002\u7ed3\u5c3e"
    )
    assert body_identity("the rapist") != body_identity("therapist")


def test_hidden_ancestor_and_advert_video_cannot_become_material(ingestion_db: IngestionDB) -> None:
    hidden = (
        '<div hidden><section id="detailContent"><p>Invisible paywalled body.</p></section></div>'
    )
    visible = (
        '<div hidden><video src="https://media.example.org/ad.mp4"></video></div>'
        '<div id="detailContent"><p>A visible text article.</p></div>'
    )
    for html, expected in ((hidden, "none"), (visible, "open_text_unit")):

        def handler(_: httpx.Request, html: str = html) -> httpx.Response:
            return httpx.Response(200, text=html)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            result = retrieve_material(
                ingestion_db.source(origin_hosts=["news.cn"]),
                {"url": "https://www.news.cn/item", "metadata": {"title": "Item"}},
                client,
                now=NOW,
            )
        assert result.scope == expected
        assert result.metadata.form == "unknown" and result.metadata.media_url is None
        assert all("Invisible" not in unit.text for unit in result.paragraphs)


def test_older_material_payload_cannot_revert_newer_metadata(ingestion_db: IngestionDB) -> None:
    source, item = ingestion_db.source(), ingestion_db.item(title="Old title")
    ingestion_db.persist(source, item)
    old = ingestion_db.take()
    old_result = material(old)
    corrected = item.model_copy(update={"title": "Corrected title"})
    ingestion_db.persist(source, corrected, cycle="correction")
    ingestion_db.finish(old, old_result)
    current = ingestion_db.take()
    ingestion_db.finish(current, material(current))
    with ingestion_db.scope() as session:
        output = apply_material(session, old, old_result)
        assert output["stale_metadata"] is True
        row = session.get(Article, old.article_id)
        assert row and row.title == "Corrected title"
    ingestion_db.persist(source, corrected, cycle="next")
    with ingestion_db.scope() as session:
        row = session.get(Article, old.article_id)
        assert row and row.title == "Corrected title"


def test_root_change_elects_one_replacement_for_multiple_unchanged_duplicates(
    ingestion_db: IngestionDB,
) -> None:
    source = ingestion_db.source()
    ingestion_db.persist(
        source, ingestion_db.item("a"), ingestion_db.item("b"), ingestion_db.item("c")
    )
    first, second, third = ingestion_db.take(), ingestion_db.take(), ingestion_db.take()
    for lease in (first, second, third):
        ingestion_db.finish(lease, material(lease))
    with ingestion_db.scope() as session:
        apply_material(
            session, first, material(first, "A changed and independently different body. " * 8)
        )
    with ingestion_db.scope() as session:
        rows = {row.id: row for row in session.scalars(select(Article))}
        assert (
            first.article_id is not None
            and second.article_id is not None
            and third.article_id is not None
        )
        assert rows[first.article_id].canonical_content_id is None
        assert rows[second.article_id].canonical_content_id is None
        assert rows[third.article_id].canonical_content_id == second.article_id


def test_redirect_to_an_alias_resolves_the_shared_canonical_root(ingestion_db: IngestionDB) -> None:
    source = ingestion_db.source()
    ingestion_db.persist(
        source, ingestion_db.item("a"), ingestion_db.item("b"), ingestion_db.item("c")
    )
    first, second, third = ingestion_db.take(), ingestion_db.take(), ingestion_db.take()
    ingestion_db.finish(first, material(first))
    ingestion_db.finish(second, material(second))
    redirected = material(third).model_copy(update={"source_url": second.payload["url"]})
    ingestion_db.finish(third, redirected)
    with ingestion_db.scope() as session:
        row = session.get(Article, third.article_id)
        assert row and row.canonical_content_id == first.article_id
        alias = session.scalar(select(ContentUrl).where(ContentUrl.url == second.payload["url"]))
        assert alias and alias.article_id == second.article_id


def test_verified_feed_fields_keep_publication_and_question_creation_separate() -> None:
    by_id = {source.id: source for source in load_sources()}
    from unspun.pipeline.discovery import feed_item
    from unspun.pipeline.feeds import FeedEntry

    at = NOW - timedelta(hours=2)
    entry = FeedEntry(
        url="https://www.36kr.com/newsflashes/123",
        title="Synthetic brief",
        published_at=at,
        published_raw=at.isoformat(),
        summary_html="Actual synthetic brief body.",
    )
    brief = feed_item(by_id["36kr-newsflashes"], entry, 1)
    assert brief.metadata.times[0].kind == "original"
    assert brief.metadata.times[0].at == at
    question = feed_item(
        by_id["zhihu-hot"],
        FeedEntry(
            url="https://www.zhihu.com/question/123",
            title="Question",
            published_at=at,
            published_raw=at.isoformat(),
            summary_html="Question background",
        ),
        1,
    )
    assert question.metadata.times[0].kind == "question_created"
    assert question.rank == 1
    assert not any(t.kind == "original" for t in question.metadata.times)


def test_feed_publication_change_does_not_refresh_recorded_original(
    ingestion_db: IngestionDB,
) -> None:
    source = ingestion_db.source()
    old = ContentTime(
        kind="original", precision="time", at=NOW - timedelta(days=10), basis="upstream:publishTime"
    )
    first = ingestion_db.item(metadata=ContentMetadata(form="article", times=(old,)))
    ingestion_db.persist(source, first)
    second = first.model_copy(
        update={
            "metadata": ContentMetadata(
                form="article",
                times=(
                    ContentTime(
                        kind="original", precision="time", at=NOW, basis="upstream:publishTime"
                    ),
                ),
            )
        }
    )
    ingestion_db.persist(source, second, cycle="changed")
    with ingestion_db.scope() as session:
        row = session.scalar(select(Article).where(Article.source_id == source.id))
        assert row
        assert row.r1_metadata is not None and old.at is not None
        times: list[dict[str, Any]] = row.r1_metadata["times"]
        assert next(value for value in times if value["kind"] == "original")[
            "at"
        ] == old.at.isoformat().replace("+00:00", "Z")
        assert any(value["kind"] == "modified" and "conflicts" in value["basis"] for value in times)
