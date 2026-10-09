from datetime import UTC, datetime

import pytest

from unspun.pipeline.extract import strip_tags
from unspun.pipeline.feeds import is_http_url, parse_feed

RSS_SAMPLE = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Sample</title>
<item>
  <title>First story</title>
  <link>https://example.com/a</link>
  <pubDate>Thu, 09 Oct 2026 08:00:00 GMT</pubDate>
  <description>&lt;p&gt;Teaser one&lt;/p&gt;</description>
</item>
<item>
  <title>Duplicate link</title>
  <link>https://example.com/a</link>
</item>
<item>
  <title>No link at all</title>
</item>
<item>
  <title>Second story</title>
  <link>https://example.com/b</link>
</item>
</channel></rss>"""

ATOM_SAMPLE = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Sample</title>
  <entry>
    <title>Atom entry</title>
    <link href="https://example.com/atom-1"/>
    <updated>2026-10-09T09:30:00Z</updated>
    <summary>Atom teaser</summary>
  </entry>
</feed>"""


def test_parse_rss_dedupes_and_skips_linkless_entries() -> None:
    entries = parse_feed(RSS_SAMPLE)
    assert [e.url for e in entries] == ["https://example.com/a", "https://example.com/b"]
    first = entries[0]
    assert first.title == "First story"
    assert first.published_at == datetime(2026, 10, 9, 8, 0, tzinfo=UTC)
    assert first.summary_html is not None
    assert "Teaser one" in first.summary_html
    assert entries[1].published_at is None


def test_parse_atom_uses_updated_timestamp() -> None:
    entries = parse_feed(ATOM_SAMPLE)
    assert len(entries) == 1
    assert entries[0].url == "https://example.com/atom-1"
    assert entries[0].published_at == datetime(2026, 10, 9, 9, 30, tzinfo=UTC)


MALICIOUS_SAMPLE = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Hostile</title>
<item>
  <title>Script link</title>
  <link>javascript:alert(1)</link>
</item>
<item>
  <title>Data link</title>
  <link>data:text/html,hi</link>
</item>
<item>
  <title>Host-less https link</title>
  <link>https:evil.example</link>
</item>
<item>
  <title>Legit story</title>
  <link>https://example.com/ok</link>
</item>
</channel></rss>"""

RELATIVE_SAMPLE = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Relative links</title>
<item>
  <title>Relative path</title>
  <link>/posts/123</link>
</item>
<item>
  <title>Scheme-relative</title>
  <link>//other.example.com/x</link>
</item>
<item>
  <title>Still hostile</title>
  <link>javascript:alert(1)</link>
</item>
</channel></rss>"""


def test_parse_feed_rejects_non_http_urls() -> None:
    entries = parse_feed(MALICIOUS_SAMPLE)
    assert [e.url for e in entries] == ["https://example.com/ok"]


def test_parse_feed_resolves_relative_urls_against_feed_url() -> None:
    entries = parse_feed(RELATIVE_SAMPLE, base_url="https://blog.example.com/feed.xml")
    assert [e.url for e in entries] == [
        "https://blog.example.com/posts/123",
        "https://other.example.com/x",
    ]


def test_parse_feed_without_base_url_drops_relative_links() -> None:
    entries = parse_feed(RELATIVE_SAMPLE)
    assert entries == []


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.com/a", True),
        ("http://example.com/a", True),
        ("javascript:alert(1)", False),
        ("data:text/html,hi", False),
        ("ftp://example.com/a", False),
        ("//example.com/a", False),
        ("/relative/path", False),
        ("", False),
        ("http:", False),
        ("https:evil", False),
        ("http:///x", False),
    ],
)
def test_is_http_url(url: str, expected: bool) -> None:
    assert is_http_url(url) is expected


def test_strip_tags_flattens_html() -> None:
    assert strip_tags("<p>Hello <b>world</b></p>  <p>again</p>") == "Hello world again"
