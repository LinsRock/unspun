import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from unspun.core.models import Article
from unspun.core.sources import Source
from unspun.pipeline.fetcher import fetch_source

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
