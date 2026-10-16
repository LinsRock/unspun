"""Editorial dates, actual bylines, and bounded RSS review material contracts."""

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.orm import Session

from unspun.core.sources import Source, load_sources
from unspun.pipeline.discovery import discover, douban_preview, feed_item, persist_discovery
from unspun.pipeline.feeds import FeedEntry
from unspun.pipeline.materials import retrieve_material

CONFIG = Path(__file__).parents[2] / "config"
NOW = datetime(2026, 10, 16, 8, tzinfo=UTC)


def source(name: str) -> Source:
    return next(s for s in load_sources(CONFIG) if s.id == name)


def payload(item: Any) -> dict[str, Any]:
    return {
        "url": str(item.url),
        "metadata": {"title": item.title, **item.metadata.model_dump(mode="json")},
        "provided_text": item.provided_text,
    }


def test_new_sources_have_no_legacy_or_r1_runtime_enabled() -> None:
    ids = {
        "zhihu-daily",
        "people-frontpage",
        "zaobao-world",
        "bjnews-depth",
        "douban-book",
        "douban-movie",
        "fortune-business",
        "fortune-tech",
        "infzm-news",
    }
    sources = [s for s in load_sources(CONFIG) if s.id in ids]
    assert len(sources) == len(ids)
    for s in sources:
        assert s.r1 and s.discovery_owner == "r1" and not s.legacy_enabled
        assert not any((s.r1.discovery, s.r1.material, s.r1.paid, s.r1.publish))


def daily_list(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "date": "20261016",
            "stories": [
                {"id": 9793275, "title": "Observed edition", "hint": "Not an actual byline"},
                {"id": 9793275, "title": "Duplicate"},
            ],
            "top_stories": [{"id": 1, "title": "Older unknown edition"}],
        },
    )


def test_daily_uses_dated_list_not_old_carousel_or_hint_author() -> None:
    with httpx.Client(transport=httpx.MockTransport(daily_list)) as client:
        result = discover(source("zhihu-daily"), client, now=NOW)
    assert len(result.items) == 1
    item = result.items[0]
    assert item.identity_namespace == "zhihu-daily:story"
    assert item.metadata.authors == ()
    assert item.metadata.times[0].kind == "editorial"
    assert item.metadata.times[0].on == date(2026, 10, 16)
    assert item.metadata.times[0].at is None


@pytest.mark.parametrize("stamp", [None, 1792134000, 10**30, True])
def test_daily_body_author_answer_link_and_publish_time_boundaries(stamp: Any) -> None:
    s = source("zhihu-daily")
    with httpx.Client(transport=httpx.MockTransport(daily_list)) as client:
        item = discover(s, client, now=NOW).items[0]
    data = {
        "id": 9793275,
        "body": '<span class="author">Real Author\uff0c</span>'
        '<div class="content"><p>Observed editorial body.</p></div>'
        '<a href="https://www.zhihu.com/question/27870891/answer/3464927278"></a>',
    }
    if stamp is not None:
        data["publish_time"] = stamp
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=data))) as c:
        result = retrieve_material(s, payload(item), c, now=NOW)
    assert result.scope == "editorial_edition" and result.completeness == "observed_unit"
    assert [p.text for p in result.paragraphs] == ["Observed editorial body."]
    assert result.metadata.authors[0].name == "Real Author"
    assert str(result.metadata.original_url).endswith("/answer/3464927278")
    assert not any(t.kind == "original" for t in result.metadata.times)
    if stamp == 1792134000:
        assert result.metadata.times[0].precision == "time"
    else:
        assert result.metadata.times[0].precision == "date"
    assert not result.evidence["original_answer_fetched"]


def test_daily_missing_body_and_restricted_are_not_fabricated_material() -> None:
    s = source("zhihu-daily")
    with httpx.Client(transport=httpx.MockTransport(daily_list)) as c:
        item = discover(s, c, now=NOW).items[0]
    for status, data in [(200, {"id": 9793275}), (403, {})]:
        with httpx.Client(
            transport=httpx.MockTransport(
                lambda _, code=status, body=data: httpx.Response(code, json=body)
            )
        ) as c:
            result = retrieve_material(s, payload(item), c, now=NOW)
        assert result.scope == "none" and not result.paragraphs
        assert result.access_status == ("restricted" if status == 403 else "unavailable")


def test_daily_identity_mismatch_fails() -> None:
    s = source("zhihu-daily")
    with httpx.Client(transport=httpx.MockTransport(daily_list)) as c:
        item = discover(s, c, now=NOW).items[0]
    with (
        httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"id": 1}))
        ) as c,
        pytest.raises(ValueError, match="identity"),
    ):
        retrieve_material(s, payload(item), c, now=NOW)


def people_http(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("index.html"):
        html = (
            '<ul id="list" style="display:none"><li><a href="202610/16/node_01.html">Front page</a>'
            '<a href="202610/16/node_02.html">Other</a></li></ul>'
        )
    else:
        html = '<a href="../../../content/202610/16/content_30185944.html">Actual article</a>'
        html += '<a href="../../../content/202610/15/content_1.html">Archive</a>'
        html += (
            '<a href="https://evil.example/rmrb/pc/content/202610/16/content_2.html">External</a>'
        )
    return httpx.Response(200, text=html)


def test_people_frontpage_uses_observed_edition_not_template_or_clock() -> None:
    with httpx.Client(transport=httpx.MockTransport(people_http)) as c:
        result = discover(source("people-frontpage"), c, now=NOW)
    assert len(result.items) == 1
    assert result.items[0].metadata.times[0].on == date(2026, 10, 16)
    assert result.items[0].metadata.times[0].at is None


def test_people_ignores_real_stale_meta_and_edition_number_author() -> None:
    s = source("people-frontpage")
    with httpx.Client(transport=httpx.MockTransport(people_http)) as c:
        item = discover(s, c, now=NOW).items[0]
    html = (
        '<meta name="publishdate" '
        'content="2013-07-17"><meta name="author" content="\u7b2c001\u7248">'
    )
    html += (
        '<div id="ozoom"><p>\u65b0\u534e\u793e\u5317\u4eac'
        "10\u670815\u65e5\u7535\uff08\u8bb0\u8005\u5f20\u4e09\uff09"
        " Reported on an earlier day.</p></div>"
    )
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, text=html))) as c:
        result = retrieve_material(s, payload(item), c, now=NOW)
    assert result.scope == "editorial_edition"
    assert result.metadata.times == item.metadata.times
    assert [a.name for a in result.metadata.authors] == ["\u5f20\u4e09"]
    assert result.metadata.authors[0].role == "reporter"


def test_people_discovery_persists_with_same_task_contract(db_session: Session) -> None:
    s = source("people-frontpage")
    with httpx.Client(transport=httpx.MockTransport(people_http)) as c:
        result = discover(s, c, now=NOW)
    # The fixture transaction rolls back; this is an explicitly migrated test DB.
    assert (
        persist_discovery(db_session, s, result, cycle="synthetic-edition")["new_candidates"] == 1
    )


def entry(**values: Any) -> FeedEntry:
    return FeedEntry(
        url=values.pop("url", "https://book.douban.com/review/1/"),
        title=values.pop("title", "Review"),
        published_at=None,
        summary_html=values.pop("summary_html", None),
        **values,
    )


def test_douban_uses_description_review_prefix_not_rating_metadata() -> None:
    s = source("douban-movie")
    item = feed_item(
        s,
        entry(
            url="https://movie.douban.com/review/1/",
            author="Reviewer",
            content_html="Reviewer book and rating only",
            summary_html=(
                "Reviewer\u8bc4\u8bba: Movie\n\u8bc4\u4ef7: "
                'Good\n\n{"blocks":[{"text":"Actual observed review prefix...'
            ),
        ),
        1,
    )
    assert item.provided_text == "Actual observed review prefix"
    assert item.metadata.genre == "review"
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: pytest.fail("preview must not fetch origin"))
    ) as c:
        result = retrieve_material(s, payload(item), c, now=NOW)
    assert result.scope == "preview" and result.completeness == "partial"
    assert "rating" not in result.paragraphs[0].text
    assert douban_preview('Reviewer\n\u8bc4\u4ef7: Good\n{"entityMap":{"x":"not review"}') is None


@pytest.mark.parametrize(
    "url,title",
    [
        ("https://www.fortunechina.com/shangye/", "Mixed authors"),
        ("https://www.fortunechina.com/keji/", ""),
    ],
)
def test_fortune_drops_category_shells_and_mixed_authors(url: str, title: str) -> None:
    with pytest.raises(ValueError):
        feed_item(
            source("fortune-business"),
            entry(url=url, title=title, author="Many concatenated authors"),
            1,
        )


def test_fortune_keeps_old_longform_and_does_not_make_feed_midnight_original() -> None:
    item = feed_item(
        source("fortune-tech"),
        entry(
            url="https://www.fortunechina.com/keji/c/2026-09/24/content_1.htm",
            published_raw="Wed, 23 Sep 2026 16:00:00 GMT",
            author="Observed Author",
        ),
        1,
    )
    assert item.metadata.times[0].kind == "feed"
    assert not any(t.kind == "original" for t in item.metadata.times)
    assert item.metadata.authors[0].name == "Observed Author"


def test_fortune_uses_chinese_body_and_visible_date_without_captions() -> None:
    s = source("fortune-business")
    item = feed_item(
        s, entry(url="https://www.fortunechina.com/shangye/c/2026-10/15/content_1.htm"), 1
    )
    html = '<div class="date">2026-10-15</div><div class="word-zh">'
    html += '<font color="gray">Photo caption</font><p>Chinese body observed.</p></div>'
    html += '<div class="word-du"><div class="word-cn">Duplicate Chinese body.</div>'
    html += '<div class="word-en">English parallel body.</div></div>'
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, text=html))) as c:
        result = retrieve_material(s, payload(item), c, now=NOW)
    assert [p.text for p in result.paragraphs] == ["Chinese body observed."]
    assert result.metadata.times[0].on == date(2026, 10, 15)
    assert result.metadata.times[0].at is None
    assert result.metadata.times[0].basis == "fortune:visible-date"


def test_explicit_reporter_and_editor_roles_do_not_collapse() -> None:
    item = feed_item(
        source("bjnews-depth"),
        entry(
            url="https://www.bjnews.com.cn/detail/1.html",
            author="\u8bb0\u8005\uff1aReporter \u7f16\u8f91\uff1aEditorA EditorB",
        ),
        1,
    )
    assert [(a.name, a.role) for a in item.metadata.authors] == [
        ("Reporter", "reporter"),
        ("EditorA", "editor"),
        ("EditorB", "editor"),
    ]


def test_daily_multiple_answers_preserve_each_body_and_author_and_failed_refresh_metadata() -> None:
    s = source("zhihu-daily")
    with httpx.Client(transport=httpx.MockTransport(daily_list)) as c:
        item = discover(s, c, now=NOW).items[0]
    html = '<div class="question"><span class="author">Alice</span>'
    html += '<div class="content"><p>First answer.</p></div></div>'
    html += '<div class="question"><span class="author">Bob</span>'
    html += '<div class="content"><p>Second answer.</p></div></div>'
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"id": 9793275, "body": html})
        )
    ) as c:
        result = retrieve_material(s, payload(item), c, now=NOW)
    assert [(p.kind, p.text) for p in result.paragraphs] == [
        ("heading", "Alice"),
        ("paragraph", "First answer."),
        ("heading", "Bob"),
        ("paragraph", "Second answer."),
    ]
    previous = payload(item)
    previous["metadata"] = {"title": item.title, **result.metadata.model_dump(mode="json")}
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"id": 9793275}))
    ) as c:
        missing = retrieve_material(s, previous, c, now=NOW)
    assert missing.scope == "none" and missing.metadata == result.metadata
    assert (
        douban_preview(
            'Reviewer\n\u8bc4\u4ef7: Good\n{"blocks":[{"text":""},'
            '{"text":"Real first paragraph."},{"text":"Second paragraph."}]}'
        )
        == "Real first paragraph.\nSecond paragraph."
    )
