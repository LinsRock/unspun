import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from unspun.core.models import Article
from unspun.core.sources import Source
from unspun.pipeline.feeds import FeedEntry
from unspun.pipeline.fetcher import drop_internal_urls, fetch_source

FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Sample</title>
<item>
  <title>First story</title>
  <link>https://example.com/a</link>
  <description>Teaser one</description>
</item>
<item>
  <title>Second story</title>
  <link>https://example.com/b</link>
  <description>Teaser two</description>
</item>
</channel></rss>"""


def make_source(max_items: int | None = None) -> Source:
    return Source(
        id="sample",
        name="Sample",
        url="https://example.com/feed",  # type: ignore[arg-type]  # pydantic coerces
        weight=0.9,
        region="us",
        kind="commercial",
        lang="en",
        max_items=max_items,
    )


def make_client() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/feed":
            return httpx.Response(200, content=FEED)
        # Article pages unavailable: forces the summary fallback path.
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_source_inserts_then_dedupes(db_session: Session) -> None:
    client = make_client()
    source = make_source()
    assert fetch_source(db_session, client, source) == 2
    assert fetch_source(db_session, client, source) == 0
    articles = list(
        db_session.scalars(
            select(Article).where(Article.source_id == "sample").order_by(Article.url)
        )
    )
    assert [a.url for a in articles] == ["https://example.com/a", "https://example.com/b"]
    assert articles[0].content == "Teaser one"
    assert articles[0].lang == "en"
    assert articles[0].source_id == "sample"


def test_fetch_source_honors_max_items(db_session: Session) -> None:
    assert fetch_source(db_session, make_client(), make_source(max_items=1)) == 1


def testdrop_internal_urls_filters_rsshub_host() -> None:
    def entry(url: str) -> FeedEntry:
        return FeedEntry(url=url, title="t", published_at=None, summary_html=None)

    entries = [
        entry("https://example.com/story"),
        entry("http://rsshub:1200/caixin/article/1"),
        entry("http://rsshub:1200"),
        # Same prefix but a different host: must be kept.
        entry("http://rsshub:12000/other"),
    ]
    kept = drop_internal_urls(entries, "http://rsshub:1200")
    assert [e.url for e in kept] == ["https://example.com/story", "http://rsshub:12000/other"]
