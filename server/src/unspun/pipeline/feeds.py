"""Fetch and parse RSS/Atom/RDF feeds into plain entry records."""

import calendar
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin, urlparse

import feedparser
import httpx

from unspun.core.logging import get_logger

log = get_logger("unspun.pipeline.feeds")

USER_AGENT = "unspun/0.1 (+https://github.com/LinsRock/unspun)"
HTTP_TIMEOUT_SECONDS = 20


@dataclass(frozen=True)
class FeedEntry:
    url: str
    title: str
    published_at: datetime | None
    summary_html: str | None
    external_id: str | None = None
    author: str | None = None
    published_raw: str | None = None
    updated_at: datetime | None = None
    updated_raw: str | None = None
    content_html: str | None = None


def make_client() -> httpx.Client:
    return httpx.Client(
        timeout=HTTP_TIMEOUT_SECONDS,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )


def is_http_url(url: str) -> bool:
    """Feed links are untrusted input; only http(s) may be stored or fetched (see D-009)."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def fetch_bytes(client: httpx.Client, url: str, timeout_seconds: int | None = None) -> bytes:
    timeout = timeout_seconds if timeout_seconds is not None else httpx.USE_CLIENT_DEFAULT
    resp = client.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.content


def parse_feed(data: bytes, base_url: str | None = None) -> list[FeedEntry]:
    parsed = feedparser.parse(data)
    entries: list[FeedEntry] = []
    seen: set[str] = set()
    for e in parsed.entries:
        url = e.get("link")
        title = e.get("title")
        if not url or not title:
            continue
        # Some feeds emit relative or scheme-relative links; resolve against the feed URL.
        if base_url:
            try:
                url = urljoin(base_url, url)
            except ValueError:
                # e.g. "Invalid IPv6 URL"; one malformed link must not kill the feed.
                log.warning("malformed_entry_url_skipped", url=url)
                continue
        if url in seen:
            continue
        seen.add(url)
        if not is_http_url(url):
            log.warning("non_http_entry_url_skipped", url=url)
            continue
        # feedparser normalizes timestamps to UTC struct_time.
        struct = e.get("published_parsed") or e.get("updated_parsed")
        published_at = datetime.fromtimestamp(calendar.timegm(struct), tz=UTC) if struct else None
        raw_entry = dict[str, Any](e)
        updated_struct = raw_entry.get("updated_parsed")
        entries.append(
            FeedEntry(
                url=url,
                title=title,
                published_at=published_at,
                summary_html=e.get("summary"),
                external_id=e.get("id"),
                author=e.get("author"),
                published_raw=e.get("published"),
                updated_at=datetime.fromtimestamp(calendar.timegm(updated_struct), tz=UTC)
                if updated_struct
                else None,
                updated_raw=raw_entry.get("updated"),
                content_html=next(
                    (item.get("value") for item in e.get("content", []) if item.get("value")), None
                ),
            )
        )
    return entries
