"""R1 metadata-first discovery; no body fetch, embedding, or model calls."""

import ipaddress
import json
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Literal, cast
from urllib.parse import unquote_plus, urlsplit, urlunsplit

import httpx
from pydantic import Field, HttpUrl
from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from unspun.core.content import Author, ContentContract, ContentMetadata, ContentTime, fingerprint
from unspun.core.html_text import visible_text
from unspun.core.models import (
    Article,
    ContentDerivation,
    ContentIdentity,
    ContentObservation,
    ContentUrl,
)
from unspun.core.sources import Source
from unspun.core.task_models import SourceState
from unspun.core.tasks import Lease, enqueue
from unspun.pipeline.feeds import FeedEntry, fetch_bytes, make_client, parse_feed

DISCOVERY_VERSION = "r1-discovery-v1"
MATERIAL_VERSION = "r1-material-v1"


def public_url(value: str) -> str:
    parts = urlsplit(str(HttpUrl(value)))
    host = parts.hostname or ""
    if (
        parts.username
        or parts.password
        or parts.port not in (None, 80, 443)
        or "." not in host
        or host.endswith((".local", ".internal", ".localhost"))
    ):
        raise ValueError("content URL must be public HTTP(S)")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise ValueError("content URL cannot use a private address")
    query = [
        part
        for part in parts.query.split("&")
        if part
        and not unquote_plus(part.partition("=")[0]).lower().startswith("utm_")
        and unquote_plus(part.partition("=")[0]).lower() not in {"fbclid", "gclid"}
    ]
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path or "/", "&".join(query), ""))


class DiscoveryItem(ContentContract):
    url: HttpUrl
    title: str = Field(min_length=1, max_length=1000)
    item_key: str = Field(min_length=1, max_length=4096)
    identity_namespace: str
    identity_value: str
    metadata: ContentMetadata
    source_excerpt: str | None = None
    provided_text: str | None = None
    provided_truncated: bool = False
    rank: int | None = Field(default=None, ge=1)
    signals: dict[str, Any] | None = None


class DiscoveryResult(ContentContract):
    source_id: str
    observed_at: datetime
    response_fingerprint: str
    items: tuple[DiscoveryItem, ...]


def _time(
    kind: Literal["feed", "modified"], raw: str | None, at: datetime | None
) -> ContentTime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(raw)
        except (ValueError, TypeError):
            return ContentTime(kind=kind, precision="unknown", raw=raw, basis="feed:unparsed")
    if parsed.utcoffset() is None:
        return ContentTime(
            kind=kind,
            precision="date",
            on=parsed.date(),
            raw=raw,
            basis="feed:" + kind + ":date_or_timezone_unknown",
        )
    return ContentTime(
        kind=kind, precision="time", at=parsed.astimezone(UTC), raw=raw, basis="feed:" + kind
    )


def feed_item(source: Source, entry: FeedEntry, rank: int) -> DiscoveryItem:
    config = source.r1
    if config is None:
        raise ValueError("R1 source capability is not declared")
    url = public_url(entry.url)
    namespace, identity = "feed:" + source.id, entry.external_id or url
    host, path = urlsplit(url).hostname or "", urlsplit(url).path
    if config.platform == "fortunechina" and not re.fullmatch(
        r"/(?:shangye|keji)/c/\d{4}-\d{2}/\d{2}/content_\d+\.htm", path
    ):
        raise ValueError("fortune entry is not an article, including category/author shells")
    form = config.form
    if (host == "zhihu.com" or host.endswith(".zhihu.com")) and (
        match := re.fullmatch(r"/question/(\d+)/?", path)
    ):
        namespace, identity, form = "zhihu:question", match[1], "question"
    elif (host == "36kr.com" or host.endswith(".36kr.com")) and (
        match := re.fullmatch(r"/newsflashes/(\d+)/?", path)
    ):
        namespace, identity = "36kr:newsflash", match[1]
    times = tuple(
        item
        for item in (
            _time("feed", entry.published_raw, entry.published_at),
            _time("modified", entry.updated_raw, entry.updated_at),
        )
        if item is not None
    )
    author = visible_text(entry.author or "").strip()
    authors = (
        (Author(name=author[:300], role="unknown", platform=config.platform, basis="feed:author"),)
        if author
        else ()
    )
    if author and config.platform in {"bjnews", "infzm"}:
        labels = r"\u8bb0\u8005|\u7f16\u8f91|\u5b9e\u4e60\u751f"
        matches = re.findall(
            rf"({labels})[\uff1a:\s]+(.*?)(?=(?:\u5357\u65b9\u5468\u672b)?(?:{labels})|$)",
            author,
        )
        if matches:
            authors = tuple(
                Author(
                    name=name,
                    role="reporter"
                    if role == "\u8bb0\u8005"
                    else "editor"
                    if role == "\u7f16\u8f91"
                    else "unknown",
                    platform=config.platform,
                    basis="feed:explicit-byline-role:" + role,
                )
                for role, names in matches
                for name in re.split(r"[\s\u3001\uff0c,]+", names.strip())
                if name
            )
    excerpt = visible_text(entry.summary_html or "").strip() or None
    provided = visible_text(entry.content_html or entry.summary_html or "").strip() or None
    if config.platform == "douban":
        # content:encoded contains only the book/movie, rating, and reviewer.
        # The description carries the actual bounded review preview, sometimes
        # as a truncated Draft.js JSON string. Never render that transport JSON.
        provided = douban_preview(entry.summary_html or "")
        excerpt = provided
    return DiscoveryItem(
        url=HttpUrl(url),
        title=visible_text(entry.title).strip(),
        item_key=identity,
        identity_namespace=namespace,
        identity_value=identity,
        metadata=ContentMetadata(
            form=form,
            genre="review" if config.platform == "douban" else None,
            platform=config.platform,
            publisher=config.publisher,
            authors=authors,
            times=times,
        ),
        source_excerpt=excerpt[:2000] if excerpt else None,
        provided_text=provided[:150000] if provided else None,
        provided_truncated=bool(provided and len(provided) > 150000),
        rank=rank if source.id == "zhihu-hot" else None,
    )


def douban_preview(description: str) -> str | None:
    value = visible_text(description).partition("\n\n")[2].strip()
    if not value:
        # visible_text normalizes blank lines; the rating line is the boundary.
        value = re.sub(r"^[\s\S]*?\u8bc4\u4ef7:[^\n]*\n?", "", visible_text(description)).strip()
    if not value.startswith("{"):
        return value or None
    try:
        document = json.loads(value)
    except ValueError:
        document = None
    if isinstance(document, dict):
        blocks = cast(dict[str, Any], document).get("blocks")
        if isinstance(blocks, list):
            texts: list[str] = []
            for block in cast(list[Any], blocks):
                text = cast(dict[str, Any], block).get("text") if isinstance(block, dict) else None
                if isinstance(text, str) and text.strip():
                    texts.append(text.strip())
            return "\n".join(texts) or None
    match = re.search(r'"text"\s*:\s*("[\s\S]*)', value)
    if not match:
        return None
    encoded = match[1]
    try:
        decoded, _ = json.JSONDecoder().raw_decode(encoded)
    except ValueError:
        # Retain only a decodable observed string prefix, not missing blocks.
        encoded = encoded.rstrip(".").rstrip("\u2026")
        if encoded.endswith("\\"):
            encoded = encoded[:-1]
        try:
            decoded = json.loads(encoded + '"')
        except ValueError:
            return None
    return decoded.strip() if isinstance(decoded, str) and decoded.strip() else None


def discover(
    source: Source, client: httpx.Client, *, now: datetime | None = None
) -> DiscoveryResult:
    if source.r1 is None:
        raise ValueError("R1 source capability is not declared")
    if source.r1.adapter != "rss":
        from unspun.pipeline.editions import discover_edition

        return discover_edition(source, client, now=now)
    data = fetch_bytes(client, str(source.url), source.timeout_seconds)
    if len(data) > 2 * 1024 * 1024:
        raise ValueError("feed exceeds discovery input bound")
    entries = parse_feed(data, str(source.url))[: source.max_items or 50]
    items: list[DiscoveryItem] = []
    for index, entry in enumerate(entries, 1):
        # Invalid entries remain outside the fetch graph, never interpreted as code.
        try:
            items.append(feed_item(source, entry, index))
        except ValueError:
            continue
    if not items:
        raise ValueError("discovery returned no valid entries")
    return DiscoveryResult(
        source_id=source.id,
        observed_at=now or datetime.now(UTC),
        response_fingerprint=fingerprint(data.hex()),
        items=tuple(items),
    )


def lock_identity(session: Session, key: str) -> None:
    number = int(fingerprint(key)[:16], 16)
    session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": number - 2**64 if number >= 2**63 else number},
    )


def observation_version(observation: ContentObservation) -> str:
    snapshot = observation.metadata_snapshot
    return fingerprint(
        {
            "url": observation.discovered_url,
            **{
                key: snapshot.get(key)
                for key in (
                    "title",
                    "metadata",
                    "provided_text_fingerprint",
                    "provided_truncated",
                    "source_excerpt",
                )
            },
        }
    )


def latest_observation(session: Session, article_id: int, source_id: str) -> ContentObservation:
    result = session.scalar(
        select(ContentObservation)
        .where(
            ContentObservation.article_id == article_id, ContentObservation.source_id == source_id
        )
        .order_by(ContentObservation.id.desc())
        .limit(1)
    )
    if result is None:
        raise ValueError("content has no matching discovery provenance")
    return result


def persist_discovery(
    session: Session, source: Source, result: DiscoveryResult, *, cycle: str
) -> dict[str, Any]:
    if source.r1 is None or result.source_id != source.id:
        raise ValueError("discovery source mismatch")
    keys = {
        key
        for item in result.items
        for key in (
            "url:" + public_url(str(item.url)),
            "identity:" + item.identity_namespace + ":" + item.identity_value,
        )
    }
    for key in sorted(keys):
        lock_identity(session, key)
    created = 0
    for item in result.items:
        url = public_url(str(item.url))
        by_identity = session.scalar(
            select(ContentIdentity).where(
                ContentIdentity.namespace == item.identity_namespace,
                ContentIdentity.external_id == item.identity_value,
            )
        )
        alias = session.scalar(select(ContentUrl).where(ContentUrl.url == url))
        if (
            by_identity is not None
            and alias is not None
            and by_identity.article_id != alias.article_id
        ):
            raise ValueError(
                "platform identity and URL alias conflict; manual reconciliation required"
            )
        identity = by_identity.article_id if by_identity else alias.article_id if alias else None
        article = (
            session.get(Article, identity)
            if identity is not None
            else session.scalar(
                select(Article).where(Article.url == url, Article.processing_track == "r1")
            )
        )
        metadata = {"title": item.title, **item.metadata.model_dump(mode="json")}
        metadata_fp = fingerprint(metadata)
        if article is None:
            article = Article(
                url=url,
                source_id=source.id,
                title=item.title,
                processing_track="r1",
                content_form=item.metadata.form,
                lang=source.lang,
                platform=item.metadata.platform,
                publisher_name=item.metadata.publisher,
                r1_metadata=metadata,
                metadata_fingerprint=metadata_fp,
                fetched_at=result.observed_at,
            )
            session.add(article)
            session.flush()
            created += 1
        if article.processing_track != "r1":
            raise ValueError("R1 identity cannot point to legacy history")
        if alias is None:
            session.add(ContentUrl(article_id=article.id, url=url, relation="discovered"))
        if by_identity is None:
            session.add(
                ContentIdentity(
                    article_id=article.id,
                    namespace=item.identity_namespace,
                    external_id=item.identity_value,
                )
            )
        # A new discovery channel is an observation, not authority to replace the
        # canonical title/byline/date of an already observed object.
        snapshot = {
            "title": item.title,
            "metadata": item.metadata.model_dump(mode="json"),
            "source_excerpt": item.source_excerpt,
            "provided_text_fingerprint": fingerprint(item.provided_text),
            "provided_truncated": item.provided_truncated,
            "response_fingerprint": result.response_fingerprint,
        }
        previous = session.scalar(
            select(ContentObservation)
            .where(
                ContentObservation.article_id == article.id,
                ContentObservation.source_id == source.id,
            )
            .order_by(ContentObservation.id.desc())
            .limit(1)
        )
        if (
            source.id == article.source_id
            and previous
            and any(
                previous.metadata_snapshot.get(key) != snapshot.get(key)
                for key in ("title", "metadata")
            )
        ):
            article.title, article.r1_metadata, article.metadata_fingerprint = (
                item.title,
                metadata,
                metadata_fp,
            )
            article.content_form = item.metadata.form
            session.execute(
                update(ContentDerivation)
                .where(
                    ContentDerivation.article_id == article.id,
                    ContentDerivation.status != "invalidated",
                )
                .values(status="invalidated", reason="discovery_metadata_changed")
            )
        session.execute(
            insert(ContentObservation)
            .values(
                article_id=article.id,
                source_id=source.id,
                item_key=item.item_key,
                discovered_url=url,
                observed_at=result.observed_at,
                observation_fingerprint=fingerprint([cycle, snapshot]),
                rank=item.rank,
                signals=item.signals,
                metadata_snapshot=snapshot,
            )
            .on_conflict_do_nothing(constraint="uq_content_observation")
        )
        if source.r1.material:
            payload = {
                "source_id": source.id,
                "discovery_version": observation_version(
                    latest_observation(session, article.id, article.source_id)
                ),
                "observation_version": observation_version(
                    latest_observation(session, article.id, source.id)
                ),
                "url": url,
                "metadata": article.r1_metadata or metadata,
                "provided_text": item.provided_text,
                "source_excerpt": item.source_excerpt,
                "provided_truncated": item.provided_truncated,
            }
            enqueue(
                session,
                queue="material",
                kind="fetch_material",
                object_key=f"content:{article.id}",
                article_id=article.id,
                source_id=source.id,
                input_fingerprint=fingerprint(payload),
                strategy_version=MATERIAL_VERSION,
                cycle_key=str(int(result.observed_at.timestamp()) // 3600),
                payload=payload,
            )
    state = session.get(SourceState, source.id)
    if state:
        state.last_item_count = len(result.items)
        if created:
            state.last_new_item_at = result.observed_at
    return {"source_id": source.id, "items": len(result.items), "new_candidates": created}


class DiscoveryHandler:
    def __init__(self, sources: dict[str, Source]) -> None:
        self.sources = sources

    def run(self, lease: Lease) -> DiscoveryResult:
        source = self.sources[lease.source_id or ""]
        if source.discovery_owner != "r1" or source.r1 is None or not source.r1.discovery:
            raise ValueError("R1 discovery stage is disabled")
        with make_client() as client:
            return discover(source, client)

    def apply(self, session: Session, lease: Lease, result: DiscoveryResult) -> dict[str, Any]:
        return persist_discovery(
            session, self.sources[result.source_id], result, cycle=str(lease.task_id)
        )
