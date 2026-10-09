from datetime import UTC, datetime

from unspun.pipeline.extract import strip_tags
from unspun.pipeline.feeds import parse_feed

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


def test_strip_tags_flattens_html() -> None:
    assert strip_tags("<p>Hello <b>world</b></p>  <p>again</p>") == "Hello world again"
