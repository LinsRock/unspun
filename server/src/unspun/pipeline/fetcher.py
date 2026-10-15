"""One fetch cycle: poll each configured source and store new articles."""

from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from unspun.core.config import get_settings
from unspun.core.db import session_scope
from unspun.core.logging import get_logger
from unspun.core.models import Article, FetchLog
from unspun.core.publication import PublicationTime, extract_publication
from unspun.core.sources import Source, load_sources
from unspun.pipeline.extract import extract_content, strip_tags
from unspun.pipeline.feeds import FeedEntry, fetch_bytes, make_client, parse_feed

log = get_logger("unspun.pipeline.fetcher")

MAX_ERROR_LENGTH = 2000


def _article_material(
    client: httpx.Client, entry: FeedEntry, fetched_at: datetime
) -> tuple[str | None, PublicationTime, str]:
    publication = PublicationTime()
    try:
        resp = client.get(entry.url)
        resp.raise_for_status()
        content = extract_content(resp.text, entry.url)
        publication = extract_publication(resp.text, str(resp.url), fetched_at)
    except Exception:
        log.warning("article_fetch_failed", url=entry.url)
        content = None
    basis = "original" if content else "unknown"
    if not content and entry.summary_html:
        content = strip_tags(entry.summary_html) or None
        basis = "feed_summary" if content else "unknown"
    return content, publication, basis


def drop_internal_urls(entries: list[FeedEntry], rsshub_base: str) -> list[FeedEntry]:
    """Drop entries whose link resolved to the internal RSSHub host.

    A relative <link> in an RSSHub feed urljoins against the feed URL and
    would otherwise be stored (and later fetched) as http://rsshub:1200/...,
    a host that only exists on the compose network.
    """
    base = rsshub_base.rstrip("/")
    kept: list[FeedEntry] = []
    for entry in entries:
        if entry.url == base or entry.url.startswith(base + "/"):
            log.warning("internal_rsshub_entry_url_dropped", url=entry.url)
            continue
        kept.append(entry)
    return kept


def fetch_source(session: Session, client: httpx.Client, source: Source) -> int:
    """Fetch one source's feed and insert unseen articles; returns new count."""
    entries = parse_feed(
        fetch_bytes(client, str(source.url), timeout_seconds=source.timeout_seconds),
        base_url=str(source.url),
    )
    entries = drop_internal_urls(entries, get_settings().rsshub_url)
    if source.max_items is not None:
        entries = entries[: source.max_items]
    if not entries:
        return 0
    known = set(
        session.scalars(select(Article.url).where(Article.url.in_([e.url for e in entries])))
    )
    new_entries: list[FeedEntry] = []
    for entry in entries:
        if entry.url not in known:
            new_entries.append(entry)
            known.add(entry.url)
    for entry in new_entries:
        fetched_at = datetime.now(UTC)
        content, publication, content_basis = _article_material(client, entry, fetched_at)
        hostname = (urlsplit(entry.url).hostname or "").lower().removeprefix("www.")
        # A hostname is a media activity proxy, not proof of independence.
        publisher = hostname or "source:" + source.id
        session.add(
            Article(
                source_id=source.id,
                url=entry.url,
                title=entry.title,
                lang=source.lang,
                published_at=entry.published_at,
                content=content,
                content_basis=content_basis,
                fetched_at=fetched_at,
                reported_at=publication.reported_at,
                reported_date=publication.reported_date,
                reported_precision=publication.precision,
                reported_basis=publication.basis,
                publisher_group=publisher,
            )
        )
    return len(new_entries)


def run_fetch_cycle() -> None:
    sources = load_sources()
    log.info("fetch_cycle_started", sources=len(sources))
    total_new = 0
    with make_client() as client:
        for source in sources:
            try:
                with session_scope() as session:
                    new_count = fetch_source(session, client, source)
                    session.add(FetchLog(source_id=source.id, status="ok", new_articles=new_count))
                total_new += new_count
                log.info("source_fetched", source=source.id, new_articles=new_count)
            except Exception as exc:
                log.exception("source_fetch_failed", source=source.id)
                with session_scope() as session:
                    session.add(
                        FetchLog(
                            source_id=source.id,
                            status="error",
                            error=str(exc)[:MAX_ERROR_LENGTH],
                        )
                    )
    log.info("fetch_cycle_finished", new_articles=total_new)
