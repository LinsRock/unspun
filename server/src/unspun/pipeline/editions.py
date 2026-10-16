"""Public editorial editions; edition dates never become original publication."""

import hashlib
import re
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

import httpx
from pydantic import HttpUrl

from unspun.core.content import Author, ContentMetadata, ContentTime, Paragraph, fingerprint
from unspun.core.html_text import TextPage, paragraphs, visible_text
from unspun.core.sources import Source
from unspun.pipeline.discovery import DiscoveryItem, DiscoveryResult, public_url

if TYPE_CHECKING:
    from unspun.pipeline.materials import MaterialResult

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _edition_date(raw: str, now: datetime) -> date:
    value = date.fromisoformat(raw)
    if value < date(1970, 1, 1) or value > now.astimezone(SHANGHAI).date() + timedelta(days=1):
        raise ValueError("edition date is outside the supported range")
    return value


def _get(source: Source, client: httpx.Client, url: str) -> httpx.Response:
    from unspun.pipeline.materials import get_page

    response = get_page(client, url, source)
    response.raise_for_status()
    return response


def discover_edition(
    source: Source, client: httpx.Client, *, now: datetime | None = None
) -> DiscoveryResult:
    config = source.r1
    if config is None:
        raise ValueError("edition capability is not declared")
    now = now or datetime.now(UTC)
    response = _get(source, client, str(source.url))
    items: list[DiscoveryItem] = []
    responses = [hashlib.sha256(response.content).hexdigest()]
    if config.adapter == "zhihu_daily":
        data: dict[str, Any] = response.json()
        raw = str(data["date"])
        if not re.fullmatch(r"\d{8}", raw):
            raise ValueError("daily list has no supported edition date")
        on = _edition_date(raw[:4] + "-" + raw[4:6] + "-" + raw[6:], now)
        seen: set[str] = set()
        # top_stories can contain older editions without their dates; only the
        # dated stories array is part of this edition's discovery contract.
        for story in data["stories"][: source.max_items or 50]:
            identity = str(story.get("id", ""))
            if not identity.isdigit() or identity in seen:
                continue
            seen.add(identity)
            title = visible_text(str(story.get("title", ""))).strip()
            if not title:
                continue
            items.append(
                DiscoveryItem(
                    url=HttpUrl("https://daily.zhihu.com/story/" + identity),
                    title=title,
                    item_key=identity,
                    identity_namespace="zhihu-daily:story",
                    identity_value=identity,
                    metadata=ContentMetadata(
                        form="article",
                        genre="editorial_edition",
                        platform=config.platform,
                        publisher=config.publisher,
                        times=(
                            ContentTime(
                                kind="editorial",
                                precision="date",
                                on=on,
                                raw=raw,
                                basis="zhihu-daily:list:date",
                            ),
                        ),
                    ),
                )
            )
    elif config.adapter == "people_daily":
        page = TextPage(response.text)
        front = next(
            (
                urljoin(str(response.url), node.attrs["href"])
                for node in page.nodes
                # The public directory is a hidden list used by its own
                # script. Only dated links are metadata here, never body.
                if node.tag == "a"
                and re.search(
                    r"/\d{6}/\d{2}/node_01\.html$",
                    urljoin(str(response.url), node.attrs.get("href", "")),
                )
            ),
            None,
        )
        if front is None:
            raise ValueError("current directory has no front-page edition")
        match = re.search(r"/(\d{4})(\d{2})/(\d{2})/node_01\.html$", front)
        if match is None:
            raise ValueError("front page has no dated identity")
        on = _edition_date("-".join(match.groups()), now)
        response = _get(source, client, front)
        responses.append(hashlib.sha256(response.content).hexdigest())
        page = TextPage(response.text)
        seen = set()
        for node in page.nodes:
            if node.excluded or node.tag != "a":
                continue
            url = urljoin(str(response.url), node.attrs.get("href", ""))
            identity_match = re.fullmatch(
                r"/rmrb/pc/content/(\d{4})(\d{2})/(\d{2})/content_(\d+)\.html",
                urlsplit(url).path,
            )
            title = " ".join(node.text().split())
            if (
                not identity_match
                or not title
                or url in seen
                or urlsplit(url).hostname != "paper.people.com.cn"
            ):
                continue
            # The layout's date is authoritative; unrelated linked archives
            # cannot inherit this edition's date or become current stories.
            if "-".join(identity_match.groups()[:3]) != on.isoformat():
                continue
            seen.add(url)
            identity = identity_match[4]
            items.append(
                DiscoveryItem(
                    url=HttpUrl(public_url(url)),
                    title=title,
                    item_key=identity,
                    identity_namespace="people:rmrb",
                    identity_value=identity,
                    metadata=ContentMetadata(
                        form="article",
                        genre="editorial_edition",
                        platform=config.platform,
                        publisher=config.publisher,
                        times=(
                            ContentTime(
                                kind="editorial",
                                precision="date",
                                on=on,
                                basis="people:frontpage:dated-layout",
                            ),
                        ),
                    ),
                )
            )
            if len(items) >= (source.max_items or 50):
                break
    else:
        raise ValueError("unknown editorial adapter")
    if not items:
        raise ValueError("edition returned no valid dated entries")
    return DiscoveryResult(
        source_id=source.id,
        observed_at=now,
        response_fingerprint=fingerprint(responses),
        items=tuple(items),
    )


def people_metadata(page: TextPage, previous: ContentMetadata) -> ContentMetadata:
    # Actual pages expose stale 2013 publishdate and an edition number as author.
    # Only visible bylines and the observed edition date may add semantics.
    authors: list[Author] = []
    node = page.by_class("author")
    if node:
        value = " ".join(node.text().split())
        if value and not re.fullmatch(r"\u7b2c\s*\d+\s*\u7248", value):
            authors.append(
                Author(
                    name=value[:300],
                    role="author",
                    platform=previous.platform,
                    basis="page:people:visible-author",
                )
            )
    body = page.by_id("ozoom")
    if body and (
        match := re.match(
            r"^\s*(?:\u672c\u62a5|\u65b0\u534e\u793e)[^\u3002]{0,100}?"
            r"[\uff08(]\u8bb0\u8005\s*([^\uff09)]+)[\uff09)]",
            body.text(),
        )
    ):
        for name in re.split(r"[\s\u3001\uff0c,]+", match[1]):
            if name:
                authors.append(
                    Author(
                        name=name[:300],
                        role="reporter",
                        platform=previous.platform,
                        basis="page:people:wire-reporter",
                    )
                )
    return previous.model_copy(update={"authors": tuple(authors) or previous.authors})


def retrieve_daily(
    source: Source, payload: dict[str, Any], client: httpx.Client, *, now: datetime
) -> "MaterialResult":
    from unspun.pipeline.materials import MaterialResult

    raw = dict(payload["metadata"])
    title = str(raw.pop("title"))
    metadata = ContentMetadata.model_validate(raw)
    match = re.fullmatch(r"/story/(\d+)/?", urlsplit(str(payload["url"])).path)
    if match is None:
        raise ValueError("daily content has no stable story identity")
    url = "https://daily.zhihu.com/api/4/news/" + match[1]
    from unspun.pipeline.materials import get_page

    response = get_page(client, url, source)
    if response.status_code >= 400:
        return MaterialResult(
            scope="none",
            access_status="restricted"
            if response.status_code in {401, 403, 429}
            else "unavailable",
            completeness="none",
            basis="zhihu-daily:detail:unavailable",
            source_url=str(payload["url"]),
            retrieved_at=now,
            response_status=response.status_code,
            response_fingerprint=hashlib.sha256(response.content).hexdigest(),
            metadata=metadata,
            title=title,
            evidence={"detail_url": url},
        )
    data: dict[str, Any] = response.json()
    if str(data.get("id")) != match[1]:
        raise ValueError("daily detail identity differs from discovery")
    page = TextPage(str(data.get("body", "")))
    bodies = [
        node
        for node in page.nodes
        if not node.excluded and "content" in node.attrs.get("class", "").split()
    ]
    units: list[Paragraph] = []
    previous_body = 0
    for body in bodies:
        body_index = next(index for index, node in enumerate(page.nodes) if node is body)
        section_authors = [
            node.text().strip().rstrip("\uff0c,")
            for node in page.nodes[previous_body:body_index]
            if not node.excluded
            and "author" in node.attrs.get("class", "").split()
            and node.text().strip().rstrip("\uff0c,")
        ]
        body_units = paragraphs(body.text())
        if body_units and len(bodies) > 1:
            units.extend(Paragraph(kind="heading", text=name) for name in section_authors)
        units.extend(Paragraph(text=value) for value in body_units)
        previous_body = body_index + 1
    authors = tuple(
        Author(
            name=node.text().strip().rstrip("\uff0c,"),
            role="author",
            platform=metadata.platform,
            basis="page:zhihu-daily:body-author",
        )
        for node in page.nodes
        if not node.excluded
        and "author" in node.attrs.get("class", "").split()
        and node.text().strip().rstrip("\uff0c,")
    )
    # An unavailable refresh is an access observation, not evidence that the
    # verified byline disappeared. Preserve metadata so material retention works.
    values: dict[str, Any] = {"authors": authors} if units else {}
    original_links = [
        public_url(node.attrs["href"])
        for node in page.nodes
        if not node.excluded
        and node.tag == "a"
        and re.fullmatch(
            r"https://www\.zhihu\.com/question/\d+/answer/\d+/?", node.attrs.get("href", "")
        )
    ]
    if original_links and units:
        values.update(
            original_url=HttpUrl(original_links[0]),
            original_relation_basis="zhihu-daily:body:answer-link",
        )
    # Some older editions expose publish_time. It is an editorial timestamp,
    # never the underlying community answer's first publication time.
    stamp = data.get("publish_time")
    if units and isinstance(stamp, (int, float)) and not isinstance(stamp, bool):
        try:
            at = datetime.fromtimestamp(stamp, UTC)
        except (ValueError, OverflowError, OSError):
            at = None
        if at and date(1970, 1, 1) <= at.date() <= now.date() + timedelta(days=1):
            values["times"] = tuple(t for t in metadata.times if t.kind != "editorial") + (
                ContentTime(
                    kind="editorial",
                    precision="time",
                    at=at,
                    basis="zhihu-daily:detail:publish_time",
                    raw=str(stamp),
                ),
            )
    return MaterialResult(
        scope="editorial_edition" if units else "none",
        access_status="ok" if units else "unavailable",
        completeness="observed_unit" if units else "none",
        basis="zhihu-daily:body:.content",
        source_url=str(payload["url"]),
        retrieved_at=now,
        response_status=response.status_code,
        response_fingerprint=hashlib.sha256(response.content).hexdigest(),
        paragraphs=tuple(units),
        source_excerpt=None,
        metadata=metadata.model_copy(update=values),
        title=title,
        evidence={
            "detail_url": url,
            "material_boundary": "daily_editorial_body",
            "original_answer_time_known": False,
            "original_answer_fetched": False,
            "publish_time_present": stamp is not None,
        },
    )
