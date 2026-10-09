"""Fetch and parse RSS/Atom/RDF feeds into plain entry records."""

import calendar
from dataclasses import dataclass
from datetime import UTC, datetime

import feedparser
import httpx

USER_AGENT = "unspun/0.1 (+https://github.com/LinsRock/unspun)"
HTTP_TIMEOUT_SECONDS = 20


@dataclass(frozen=True)
class FeedEntry:
    url: str
    title: str
    published_at: datetime | None
    summary_html: str | None


def make_client() -> httpx.Client:
    return httpx.Client(
        timeout=HTTP_TIMEOUT_SECONDS,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )


def fetch_bytes(client: httpx.Client, url: str) -> bytes:
    resp = client.get(url)
    resp.raise_for_status()
    return resp.content


def parse_feed(data: bytes) -> list[FeedEntry]:
    parsed = feedparser.parse(data)
    entries: list[FeedEntry] = []
    seen: set[str] = set()
    for e in parsed.entries:
        url = e.get("link")
        title = e.get("title")
        if not url or not title or url in seen:
            continue
        seen.add(url)
        # feedparser normalizes timestamps to UTC struct_time.
        struct = e.get("published_parsed") or e.get("updated_parsed")
        published_at = datetime.fromtimestamp(calendar.timegm(struct), tz=UTC) if struct else None
        entries.append(
            FeedEntry(
                url=url,
                title=title,
                published_at=published_at,
                summary_html=e.get("summary"),
            )
        )
    return entries
