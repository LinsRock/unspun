"""One fetch cycle: poll each configured source and store new articles."""

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from unspun.core.db import session_scope
from unspun.core.logging import get_logger
from unspun.core.models import Article, FetchLog
from unspun.core.sources import Source, load_sources
from unspun.pipeline.extract import extract_content, strip_tags
from unspun.pipeline.feeds import FeedEntry, fetch_bytes, make_client, parse_feed

log = get_logger("unspun.pipeline.fetcher")

MAX_ERROR_LENGTH = 2000


def _article_content(client: httpx.Client, entry: FeedEntry) -> str | None:
    try:
        resp = client.get(entry.url)
        resp.raise_for_status()
        content = extract_content(resp.text, entry.url)
    except Exception:
        log.warning("article_fetch_failed", url=entry.url)
        content = None
    if not content and entry.summary_html:
        content = strip_tags(entry.summary_html) or None
    return content


def fetch_source(session: Session, client: httpx.Client, source: Source) -> int:
    """Fetch one source's feed and insert unseen articles; returns new count."""
    entries = parse_feed(
        fetch_bytes(client, str(source.url), timeout_seconds=source.timeout_seconds),
        base_url=str(source.url),
    )
    if source.max_items is not None:
        entries = entries[: source.max_items]
    if not entries:
        return 0
    known = set(
        session.scalars(select(Article.url).where(Article.url.in_([e.url for e in entries])))
    )
    new_entries = [e for e in entries if e.url not in known]
    for entry in new_entries:
        session.add(
            Article(
                source_id=source.id,
                url=entry.url,
                title=entry.title,
                lang=source.lang,
                published_at=entry.published_at,
                content=_article_content(client, entry),
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
