"""Bounded public lists and source-specific provenance; no model or login."""

import json
import math
import re
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, cast
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

import httpx
from pydantic import HttpUrl

from unspun.core.content import Author, ContentMetadata, ContentTime, fingerprint
from unspun.core.html_text import TextNode, TextPage, visible_text
from unspun.core.sources import Source
from unspun.pipeline.discovery import DiscoveryItem, DiscoveryResult, public_url

VERSION = "r1-public-sources-v1"
SHANGHAI = ZoneInfo("Asia/Shanghai")


def _text(value: object) -> str:
    return visible_text(value).strip() if isinstance(value, str) else ""


def _dict(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("public source field is not an object")
    return cast(dict[str, Any], value)


def _rows(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [cast(dict[str, Any], row) for row in cast(list[object], value) if isinstance(row, dict)]


def _nodes(node: TextNode) -> Iterator[TextNode]:
    if not node.text().strip():
        return
    yield node
    for child in node.children:
        if isinstance(child, TextNode):
            yield from _nodes(child)


def _time(
    raw: object,
    now: datetime,
    basis: str,
    kind: Literal["feed", "original", "reprint"] = "feed",
) -> tuple[ContentTime, ...]:
    if not isinstance(raw, (str, int)) or isinstance(raw, bool):
        return ()
    try:
        if isinstance(raw, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            on = date.fromisoformat(raw)
            if date(1970, 1, 1) <= on <= now.astimezone(SHANGHAI).date() + timedelta(days=1):
                return (ContentTime(kind=kind, precision="date", on=on, raw=raw, basis=basis),)
            return ()
        if isinstance(raw, int):
            at = datetime.fromtimestamp(raw / 1000, UTC)
        else:
            at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if at.tzinfo is None:
                at = at.replace(tzinfo=SHANGHAI)
                basis += ":Asia/Shanghai"
    except (ValueError, OverflowError, OSError):
        return ()
    if not datetime(1970, 1, 1, tzinfo=UTC) <= at <= now + timedelta(days=1):
        return ()
    return (ContentTime(kind=kind, precision="time", at=at, raw=str(raw), basis=basis),)


def _duration(raw: object) -> float | None:
    if not isinstance(raw, (str, int, float)) or isinstance(raw, bool):
        return None
    try:
        parts = str(raw).split(":")
        if len(parts) > 3 or (
            len(parts) > 1 and any(not part.isdigit() or int(part) >= 60 for part in parts[1:])
        ):
            return None
        value = (
            float(parts[0])
            if len(parts) == 1
            else sum(float(part) * 60**index for index, part in enumerate(reversed(parts)))
        )
    except ValueError:
        return None
    return value if math.isfinite(value) and value >= 0 else None


def _qq_url(raw: str, identity: str) -> str:
    value = public_url(raw)
    parts = urlsplit(value)
    if parts.hostname not in {"new.qq.com", "news.qq.com", "view.inews.qq.com"} or (
        parts.path.rstrip("/") not in {"/rain/a/" + identity, "/a/" + identity}
    ):
        raise ValueError("Tencent item URL does not match its public article identity")
    return value


def discover_public(
    source: Source, client: httpx.Client, *, now: datetime | None = None
) -> DiscoveryResult:
    from unspun.pipeline.materials import get_page

    config = source.r1
    if config is None:
        raise ValueError("public source capability is not declared")
    now = now or datetime.now(UTC)
    response = get_page(client, str(source.url), source)
    response.raise_for_status()
    items: list[DiscoveryItem] = []
    listed = scanned = duplicates = 0
    seen: set[str] = set()
    if config.adapter == "netease":
        top = TextPage(response.text).by_id("js_top_news")
        if top is None:
            raise ValueError("NetEase current headline container is missing")
        links = [node for node in _nodes(top) if node.tag == "a"]
        listed = len(links)
        for node in links[: source.scan_limit] if config.quotas else links:
            scanned += 1
            value = urljoin(str(response.url), node.attrs.get("href", ""))
            parts = urlsplit(value)
            match = re.fullmatch(r"/(?:news|dy)/article/([A-Z0-9]{16})\.html", parts.path)
            if parts.hostname not in {"www.163.com", "news.163.com"} or not match:
                continue
            identity, title = match[1], node.text().strip()
            if not title or len(title) > 1000:
                continue
            if identity in seen:
                duplicates += 1
                continue
            seen.add(identity)
            items.append(
                DiscoveryItem(
                    url=HttpUrl(public_url(value)),
                    title=title,
                    item_key=identity,
                    identity_namespace="netease:article",
                    identity_value=identity,
                    metadata=ContentMetadata(form="article", platform="netease"),
                )
            )
    else:
        data = _dict(response.json())
        rows: list[tuple[str, dict[str, Any]]] = []
        if config.adapter == "thepaper":
            if type(data.get("resultCode")) is not int or data["resultCode"] != 1:
                raise ValueError("The Paper list returned a business failure")
            groups = _dict(data.get("data"))
            for group in ("editorHandpicked", "hotNews", "podcastNews"):
                rows.extend((group, row) for row in _rows(groups.get(group)))
        elif config.adapter == "tencent":
            code = data.get("code", data.get("ret"))
            if type(code) is not int or code != 0:
                raise ValueError("Tencent list returned a business failure")
            payload = data.get("data")
            if isinstance(payload, list):
                for group in _rows(cast(list[object], payload)):
                    if group:
                        rows.extend(("headlines", row) for row in _rows(group.get("article_list")))
            elif isinstance(payload, dict):
                rows.extend(
                    ("selected", row)
                    for row in _rows(cast(dict[str, Any], payload).get("articleList"))
                )
        else:
            raise ValueError("unsupported public source adapter")
        listed = len(rows)
        for group, row in rows[: source.scan_limit] if config.quotas else rows:
            scanned += 1
            try:
                identity = str(row.get("contId" if config.adapter == "thepaper" else "id", ""))
                title = _text(row.get("name" if config.adapter == "thepaper" else "title"))
                if not title:
                    continue
                if config.adapter == "thepaper":
                    if not identity.isdigit() or str(row.get("isOutForward", "0")) != "0":
                        continue
                    metadata = ContentMetadata(
                        platform="thepaper",
                        form="audio"
                        if group == "podcastNews"
                        else "article"
                        if row.get("contType") == 0
                        else "unknown",
                        times=_time(
                            row.get("pubTimeLong"), now, "thepaper:rightSidebar:pubTimeLong"
                        ),
                    )
                    item = DiscoveryItem(
                        url=HttpUrl("https://www.thepaper.cn/newsDetail_forward_" + identity),
                        title=title,
                        item_key=identity,
                        identity_namespace="thepaper:content",
                        identity_value=identity,
                        metadata=metadata,
                    )
                else:
                    if not re.fullmatch(r"\d{8}[A-Z][A-Z0-9]{7}", identity):
                        continue
                    links = _dict(row.get("link_info") or {})
                    value = _qq_url(str(row.get("url") or links.get("url") or ""), identity)
                    video = _dict(row.get("video_info") or {})
                    media = _dict(row.get("media_info") or {})
                    is_video = (
                        bool(video.get("vid"))
                        or str(row.get("article_type", row.get("articletype"))) == "4"
                    )
                    account = str(media.get("chl_name") or "").strip()
                    excerpt = _text(row.get("desc") or video.get("desc"))
                    # A repeated headline is metadata, not a description body.
                    provided = excerpt if excerpt and excerpt != title else None
                    item = DiscoveryItem(
                        url=HttpUrl(value),
                        title=title,
                        item_key=identity,
                        identity_namespace="tencent:article",
                        identity_value=identity,
                        source_excerpt=provided,
                        provided_text=provided,
                        metadata=ContentMetadata(
                            platform="tencent",
                            form="video" if is_video else "article",
                            times=_time(
                                row.get("publish_time"), now, "tencent:list:platform-publish-time"
                            ),
                            authors=(
                                Author(
                                    name=account,
                                    role="account",
                                    platform="tencent",
                                    platform_id=str(media.get("chl_id"))
                                    if media.get("chl_id")
                                    else None,
                                    basis="tencent:list:media_info",
                                ),
                            )
                            if account
                            else (),
                            media_url=HttpUrl(_qq_url(value, identity)) if is_video else None,
                            duration_seconds=_duration(video.get("duration")) if is_video else None,
                        ),
                    )
            except (ValueError, TypeError, AttributeError):
                continue
            if identity in seen:
                duplicates += 1
                continue
            seen.add(identity)
            items.append(item)
    if not items:
        raise ValueError("public discovery returned no valid entries")
    return DiscoveryResult(
        source_id=source.id,
        observed_at=now,
        response_fingerprint=fingerprint(response.content.hex()),
        items=tuple(items[: source.scan_limit]),
        scan_counts={
            "listed": listed,
            "scanned": scanned,
            "valid": len(items) + duplicates,
            "adapter_duplicates": duplicates,
        }
        if config.quotas
        else None,
    )


def public_material(
    page: TextPage, html: str, url: str, previous: ContentMetadata, now: datetime
) -> tuple[ContentMetadata, str, str]:
    from unspun.pipeline.materials import publication_times

    values = previous.model_dump()
    if previous.platform == "thepaper":
        match = re.search(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', html, re.S)
        if not match:
            raise ValueError("The Paper detail data is missing")
        try:
            detail = _dict(
                json.loads(match[1])["props"]["pageProps"]["detailData"]["contentDetail"]
            )
        except (KeyError, TypeError) as error:
            raise ValueError("The Paper detail structure is missing") from error
        expected = re.fullmatch(r"/newsDetail_forward_(\d+)", urlsplit(url).path)
        if not expected or str(detail.get("contId")) != expected[1]:
            raise ValueError("The Paper detail identity does not match the requested article")
        raw_body = detail.get("content")
        body = TextPage(raw_body if isinstance(raw_body, str) else "").root.text()
        author = _text(detail.get("author"))
        publisher = _text(detail.get("source")) or None
        names, separator, credited = author.partition("/")
        if separator and credited:
            publisher = credited.strip() or publisher
        labelled = re.fullmatch(
            r"(?:\u6f8e\u6e43\u65b0\u95fb)?(\u8bb0\u8005|\u7f16\u8f91)\s+(.+)", names
        )
        role: Literal["author", "reporter", "editor"] = (
            "reporter"
            if labelled and labelled[1] == "\u8bb0\u8005"
            else "editor"
            if labelled
            else "author"
        )
        names = labelled[2] if labelled else names
        if names in {"\u6f8e\u6e43\u65b0\u95fb", "\u65b0\u534e\u793e", "\u592e\u89c6\u65b0\u95fb"}:
            publisher = publisher or names
            names = ""
        values["authors"] = tuple(
            Author(name=name, role=role, platform="thepaper", basis="thepaper:detail:author")
            for name in re.split(r"[\u3001\uff0c,\s]+", names)
            if name
        )
        values["publisher"] = publisher
        kind = (
            "original"
            if detail.get("originalFlag") == "1"
            else "reprint"
            if detail.get("originalFlag") == "2"
            else "feed"
        )
        for at in _time(
            detail.get("publishTime"),
            now,
            "thepaper:detail:publishTime:originalFlag=" + str(detail.get("originalFlag")),
            kind,
        ):
            values["times"] = publication_times(previous.times, at)
        if detail.get("contType") == 25:
            values["form"] = "audio"
            media = str(detail.get("podcastAudioUrl") or "")
            if media:
                values["media_url"] = public_url(media)
            values["duration_seconds"] = _duration(detail.get("podcastAudioDuration"))
        # voiceInfo exists on ordinary articles too; it is not podcast evidence.
        return _credit_metadata(values, body), body, "thepaper:detail:content"
    if previous.platform == "netease":
        body_node, info = page.by_class("post_body"), page.by_class("post_info")
        if body_node is None or info is None:
            return previous, "", "netease:post_body:missing"
        links = [node for node in _nodes(info) if node.tag == "a" and not node.attrs.get("class")]
        if links:
            publisher = links[0].text().strip()
            values["publisher"] = publisher or None
            original = links[0].attrs.get("href", "")
            if (
                original
                and urlsplit(original).hostname
                and not (urlsplit(original).hostname or "").endswith("163.com")
            ):
                values["original_url"] = public_url(original)
                values["original_relation_basis"] = "netease:visible-source-link"
        raw = page.meta("article:published_time")
        for at in _time(
            raw,
            now,
            "netease:platform-publication:original-unverified",
            "reprint" if values.get("original_url") else "feed",
        ):
            values["times"] = publication_times(previous.times, at)
        return _credit_metadata(values, body_node.text()), body_node.text(), "netease:.post_body"
    if previous.platform == "tencent":
        body_node = page.by_id("article-content")
        account = page.by_class("media-name")
        if account and not previous.authors:
            name = account.text().strip()
            if name:
                values["authors"] = (
                    Author(
                        name=name,
                        role="account",
                        platform="tencent",
                        basis="tencent:visible-account",
                    ),
                )
        for at in _time(
            page.meta("article:published_time"),
            now,
            "tencent:platform-publication:original-unverified",
        ):
            values["times"] = publication_times(previous.times, at)
        body = body_node.text() if body_node else ""
        return _credit_metadata(values, body), body, "tencent:#article-content"
    raise ValueError("unsupported public material source")


def _credit_metadata(values: dict[str, Any], body: str) -> ContentMetadata:
    authors = list(ContentMetadata.model_validate(values).authors)
    wire = re.match(
        r"^\s*\u65b0\u534e\u793e[^\u3002]{0,80}\u7535[\uff08(]\u8bb0\u8005([^\uff09)]+)[\uff09)]",
        body,
    )
    credits: list[tuple[Literal["author", "reporter", "editor"], str]] = (
        [("reporter", wire[1])] if wire else []
    )
    credits.extend(
        ("author", names)
        for names in re.findall(
            r"(?m)^\s*\u6267\u7b14[\uff5c\u4e28|\uff1a:\s]+"
            r"([\u3400-\u9fff]{2,4}(?:[\u3001\uff0c,\s]+[\u3400-\u9fff]{2,4})*)\s*$",
            body,
        )
    )
    for role, names in credits:
        for name in re.split(r"[\u3001\uff0c,\s]+", names.strip()):
            if name:
                authors = [
                    author for author in authors if author.name != name or author.role == "account"
                ]
                authors.append(
                    Author(
                        name=name,
                        role=role,
                        platform=values.get("platform"),
                        basis=VERSION + ":explicit-visible-credit",
                    )
                )
    values["authors"] = tuple(authors)
    return ContentMetadata.model_validate(values)
