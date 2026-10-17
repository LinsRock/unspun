"""Public list business status, identity, time and actual material boundaries."""

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from unspun.core.content import ContentMetadata, ContentTime
from unspun.core.sources import Source, load_sources
from unspun.pipeline.discovery import discover
from unspun.pipeline.materials import retrieve_material

NOW = datetime(2026, 10, 17, 8, tzinfo=UTC)
STORY = "20261017V03N7T00"
NETEASE = "L9EQ37VT000189FH"


def source(adapter: str) -> Source:
    urls = {
        "thepaper": "https://cache.thepaper.cn/contentapi/wwwIndex/rightSidebar",
        "netease": "https://news.163.com/",
        "tencent": "https://i.news.qq.com/web_feed/get_command_pagination?page=1",
    }
    return Source.model_validate(
        {
            "id": adapter,
            "name": adapter,
            "url": urls[adapter],
            "weight": 1,
            "region": "cn-mainland",
            "kind": "commercial",
            "lang": "zh",
            "legacy_enabled": False,
            "r1": {
                "adapter": adapter,
                "platform": adapter,
                "origin_hosts": [
                    {"thepaper": "thepaper.cn", "netease": "163.com", "tencent": "qq.com"}[adapter]
                ],
            },
        }
    )


def json_client(value: Any) -> httpx.Client:
    return httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=value))
    )


def material(
    adapter: str, html: str, *, metadata: ContentMetadata | None = None, identity: str = "1"
) -> Any:
    urls = {
        "thepaper": "https://www.thepaper.cn/newsDetail_forward_" + identity,
        "netease": "https://www.163.com/news/article/" + NETEASE + ".html",
        "tencent": "https://news.qq.com/rain/a/" + STORY,
    }
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text=html))
    ) as client:
        return retrieve_material(
            source(adapter),
            {
                "url": urls[adapter],
                "metadata": {
                    "title": "Title",
                    **(metadata or ContentMetadata(form="article", platform=adapter)).model_dump(
                        mode="json"
                    ),
                },
            },
            client,
            now=NOW,
        )


def paper_html(**detail: Any) -> str:
    value = {"props": {"pageProps": {"detailData": {"contentDetail": detail}}}}
    return (
        '<meta name="author" content="Platform"><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(value)
        + "</script>"
    )


def test_current_paper_groups_preserve_identity_and_do_not_promote_narration() -> None:
    row = {
        "contId": "1",
        "name": "Current report",
        "contType": 0,
        "pubTimeLong": int(NOW.timestamp() * 1000),
        "voiceInfo": {"voiceSrc": "https://audios.thepaper.cn/read.mp3"},
    }
    data = {
        "resultCode": 1,
        "data": {
            "editorHandpicked": [row],
            "hotNews": [row, {**row, "contId": "3", "isOutForward": "1"}],
            "podcastNews": [
                {"contId": "2", "name": "Podcast", "contType": 25, "pubTime": "yesterday"}
            ],
        },
    }
    with json_client(data) as client:
        result = discover(source("thepaper"), client, now=NOW)
    assert [item.identity_value for item in result.items] == ["1", "2"]
    assert result.items[0].metadata.form == "article"
    assert result.items[0].metadata.media_url is None
    assert result.items[0].metadata.times[0].kind == "feed"
    assert result.items[1].metadata.form == "audio"
    assert not result.items[1].metadata.times
    assert all(item.provided_text is None for item in result.items)


@pytest.mark.parametrize(
    "data",
    [
        {"code": 10004, "data": []},
        {"ret": 10004},
        {"code": False},
        {"code": 0, "data": []},
        [],
        {"resultCode": 1},
    ],
)
def test_http_200_does_not_hide_tencent_business_failure_or_empty_list(data: Any) -> None:
    with json_client(data) as client, pytest.raises(ValueError):
        discover(source("tencent"), client, now=NOW)


def test_tencent_video_identity_account_duration_and_title_only_material() -> None:
    row = {
        "id": STORY,
        "title": "Video headline",
        "desc": "Video headline",
        "publish_time": "2026-10-17 09:04:08",
        "link_info": {"url": "https://view.inews.qq.com/a/" + STORY},
        "video_info": {"vid": "real-video-id", "duration": "01:39"},
        "media_info": {"chl_name": "Broadcaster", "chl_id": "123"},
    }
    with json_client(
        {
            "ret": 0,
            "data": {
                "articleList": [
                    row,
                    row,
                    {**row, "id": "20261017V03MRJ00", "link_info": {"url": "https://example.com/"}},
                ]
            },
        }
    ) as client:
        result = discover(source("tencent"), client, now=NOW)
    assert len(result.items) == 1
    item = result.items[0]
    assert item.metadata.form == "video" and item.metadata.duration_seconds == 99
    assert item.metadata.authors[0].role == "account"
    assert item.metadata.authors[0].platform_id == "123"
    assert item.metadata.publisher is None and item.provided_text is None
    assert item.metadata.times[0].kind == "feed"


def test_tencent_nested_headlines_do_not_infer_original_date_from_identity() -> None:
    row = {
        "id": STORY,
        "title": "Report",
        "url": "https://new.qq.com/rain/a/" + STORY,
        "article_type": "0",
    }
    with json_client(
        {"code": 0, "data": [{"article_list": [row, {**row, "title": None}]}]}
    ) as client:
        result = discover(source("tencent"), client, now=NOW)
    assert len(result.items) == 1
    assert not result.items[0].metadata.times
    assert result.items[0].metadata.publisher is None


def test_date_only_tencent_publication_does_not_invent_midnight() -> None:
    row = {
        "id": STORY,
        "title": "Report",
        "url": "https://new.qq.com/rain/a/" + STORY,
        "publish_time": "2026-10-17",
    }
    with json_client({"code": 0, "data": [{"article_list": [row]}]}) as client:
        at = discover(source("tencent"), client, now=NOW).items[0].metadata.times[0]
    assert at.precision == "date" and at.at is None and str(at.on) == "2026-10-17"


def test_netease_discovers_only_current_container_and_supported_public_stories() -> None:
    link = f'<a href="https://www.163.com/news/article/{NETEASE}.html">Current report</a>'
    html = (
        '<a href="https://www.163.com/news/article/OLDSTORY000189FH.html">Old ranking</a>'
        '<div id="js_top_news">'
        + link
        + link
        + '<div hidden><a href="https://www.163.com/news/article/L9EGK3EP000189FH.html">'
        'Hidden</a></div><a href="http://127.0.0.1/article/">Private</a>'
        '<a href="https://www.163.com/special/rank.html">Ranking</a></div>'
    )
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text=html))
    ) as client:
        result = discover(source("netease"), client, now=NOW)
    assert len(result.items) == 1 and result.items[0].identity_value == NETEASE
    assert not result.items[0].metadata.times


def test_paper_reprint_byline_and_regular_article_audio_are_distinct() -> None:
    result = material(
        "thepaper",
        paper_html(
            contId=1,
            author="Lin/Wire Agency",
            originalFlag="2",
            publishTime=int(NOW.timestamp() * 1000),
            content="<p>Actual report.</p>",
            contType=0,
            voiceInfo={"voiceSrc": "https://audios.thepaper.cn/read.mp3"},
        ),
    )
    assert result.scope == "open_text_unit"
    assert result.metadata.publisher == "Wire Agency"
    assert result.metadata.authors[0].name == "Lin"
    assert result.metadata.media_url is None and result.metadata.form == "article"
    assert [at.kind for at in result.metadata.times] == ["reprint"]


def test_podcast_uses_actual_description_media_and_publisher_fields() -> None:
    result = material(
        "thepaper",
        paper_html(
            contId=1,
            author="\u6f8e\u6e43\u65b0\u95fb\u7f16\u8f91 Chen",
            source="The Paper",
            originalFlag="1",
            publishTime=int(NOW.timestamp() * 1000),
            contType=25,
            content="<p>Published episode description, without a transcript.</p>",
            podcastAudioUrl="https://audios.thepaper.cn/episode.mp3",
            podcastAudioDuration="1636.032",
        ),
    )
    assert result.scope == "media_description" and result.completeness == "partial"
    assert result.metadata.authors[0].role == "editor"
    assert result.metadata.duration_seconds == 1636.032
    assert str(result.metadata.media_url).endswith("/episode.mp3")
    assert result.metadata.times[0].kind == "original"


def test_wrong_paper_detail_identity_never_becomes_material() -> None:
    result = material("thepaper", paper_html(contId=2, content="<p>Different article.</p>"))
    assert result.scope == "none" and result.access_status == "failed"
    assert not result.paragraphs


def test_paper_publisher_only_byline_does_not_invent_a_personal_author() -> None:
    result = material(
        "thepaper",
        paper_html(
            contId=1, author="\u6f8e\u6e43\u65b0\u95fb", content="<p>Report.</p>", contType=0
        ),
    )
    assert result.metadata.publisher == "\u6f8e\u6e43\u65b0\u95fb"
    assert not result.metadata.authors


def test_netease_reprint_and_source_link_do_not_replace_original_time() -> None:
    original = ContentTime(
        kind="original",
        precision="time",
        at=datetime(2026, 10, 14, 5, tzinfo=UTC),
        basis="verified-origin",
    )
    html = (
        '<meta name="author" content="NetEase"><meta property="article:published_time" '
        'content="2026-10-17T13:35:13+08:00"><div class="post_info">Source: '
        '<a href="https://www.news.cn/story.html">Wire Agency</a></div>'
        '<div class="post_body"><p>Actual original text remains available.</p></div>'
    )
    result = material(
        "netease",
        html,
        metadata=ContentMetadata(form="article", platform="netease", times=(original,)),
    )
    assert result.metadata.times[0] == original
    assert result.metadata.times[1].kind == "reprint"
    assert result.metadata.publisher == "Wire Agency" and not result.metadata.authors
    assert result.metadata.original_relation_basis == "netease:visible-source-link"


def test_tencent_visible_account_is_not_the_reporter_or_original_publisher() -> None:
    html = (
        '<meta name="author" content="Tencent"><meta property="article:published_time" '
        'content="2026-10-17 09:00:00"><p class="media-name">Broadcaster account</p>'
        '<div id="article-content"><p>Actual report.</p></div>'
    )
    result = material("tencent", html)
    assert result.metadata.authors[0].role == "account"
    assert result.metadata.publisher is None
    assert result.metadata.times[0].kind == "feed"


@pytest.mark.parametrize("adapter", ["thepaper", "netease", "tencent"])
def test_script_shell_does_not_become_reading_material(adapter: str) -> None:
    result = material(
        adapter,
        '<html><meta name="author" content="Platform"><script>window.shell = true</script>'
        "<p>Navigation</p></html>",
    )
    assert result.scope == "none" and not result.paragraphs


def test_new_source_configuration_is_observation_only_and_preserves_legacy_paper() -> None:
    sources = {value.id: value for value in load_sources()}
    for name in ["thepaper-sidebar", "netease-home", "tencent-headlines", "tencent-selected"]:
        entry = sources[name]
        assert entry.r1 is not None and not entry.legacy_enabled
        assert not any((entry.r1.discovery, entry.r1.material, entry.r1.paid, entry.r1.publish))
        assert entry.r1.paid_scopes == () and entry.r1.publish_scopes == ()
    assert str(sources["thepaper"].url) == "https://feedx.net/rss/thepaper.xml"
