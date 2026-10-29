"""Independent, versioned material retrieval and deterministic exact-body reuse."""

import hashlib
import json
import re
import unicodedata
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, cast
from urllib.parse import urljoin, urlsplit

import httpx
from pydantic import Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from unspun.core.content import (
    Author,
    ContentContract,
    ContentMetadata,
    ContentTime,
    Paragraph,
    fingerprint,
)
from unspun.core.html_text import TextPage, paragraphs
from unspun.core.models import Article, ContentDerivation, ContentMaterial, ContentUrl
from unspun.core.publication import extract_publication
from unspun.core.sources import Source
from unspun.core.task_models import DiscoveryBatch
from unspun.core.tasks import Lease
from unspun.pipeline.discovery import (
    MATERIAL_VERSION,
    latest_observation,
    lock_identity,
    observation_version,
    public_url,
)
from unspun.pipeline.extract import extract_content
from unspun.pipeline.feeds import make_client


class MaterialResult(ContentContract):
    scope: str
    access_status: Literal["ok", "restricted", "unavailable", "failed"]
    completeness: Literal["observed_unit", "partial", "none", "unknown"]
    basis: str
    source_url: str
    retrieved_at: datetime
    response_status: int | None = None
    response_fingerprint: str | None = None
    paragraphs: tuple[Paragraph, ...] = ()
    source_excerpt: str | None = None
    metadata: ContentMetadata
    title: str
    evidence: dict[str, Any] = Field(default_factory=dict)


def _allowed(url: str, source: Source) -> str:
    value = public_url(url)
    hosts = source.r1.origin_hosts if source.r1 else ()
    host = urlsplit(value).hostname or ""
    if not hosts or not any(host == item or host.endswith("." + item) for item in hosts):
        raise ValueError("material URL host is outside the declared public source boundary")
    return value


def get_page(client: httpx.Client, url: str, source: Source) -> httpx.Response:
    current = _allowed(url, source)
    for _ in range(6):
        # Validate each redirect before fetching it; feed-provided URLs never get
        # access to the internal RSSHub/database network or arbitrary origins.
        with client.stream(
            "GET", current, follow_redirects=False, timeout=source.timeout_seconds or 20
        ) as response:
            if response.status_code in {301, 302, 303, 307, 308}:
                current = _allowed(urljoin(current, response.headers.get("location", "")), source)
                continue
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > 2 * 1024 * 1024:
                    raise ValueError("material response exceeds input bound")
                chunks.append(chunk)
            return httpx.Response(
                response.status_code,
                headers={
                    key: value
                    for key, value in response.headers.items()
                    if key.lower() not in {"content-encoding", "content-length"}
                },
                content=b"".join(chunks),
                request=response.request,
            )
    raise ValueError("material redirect limit reached")


def publication_times(
    previous: tuple[ContentTime, ...], observed: ContentTime
) -> tuple[ContentTime, ...]:
    known = [value for value in previous if value.kind == observed.kind]
    if observed.kind == "original" and known:
        if any((value.at, value.on) == (observed.at, observed.on) for value in known):
            return previous
        # A changed publication field is not evidence that an old story became
        # newly original. Preserve the recorded original and expose the conflict.
        changed = observed.model_copy(
            update={
                "kind": "modified",
                "basis": str(observed.basis) + ":conflicts_with_recorded_original",
            }
        )
        return previous if changed in previous else previous + (changed,)
    return tuple(value for value in previous if value.kind != observed.kind) + (observed,)


def _metadata(
    page: TextPage, html: str, url: str, now: datetime, previous: ContentMetadata
) -> ContentMetadata:
    if (urlsplit(url).hostname or "").endswith("paper.people.com.cn"):
        from unspun.pipeline.editions import people_metadata

        return people_metadata(page, previous)
    values = previous.model_dump()
    authors = list(previous.authors)
    byline = page.meta("author")
    if byline and not authors:
        authors.append(
            Author(
                name=byline[:300],
                role="author",
                platform=previous.platform,
                basis="page:meta:author",
            )
        )
    values["authors"] = tuple(authors)
    publication = extract_publication(html, url, now)
    if publication.precision != "unknown":
        values["times"] = publication_times(
            previous.times,
            ContentTime(
                kind="original",
                precision=publication.precision,
                at=publication.reported_at,
                on=publication.reported_date if publication.reported_at is None else None,
                basis=publication.basis,
            ),
        )
    host = urlsplit(url).hostname or ""
    if host == "fortunechina.com" or host.endswith(".fortunechina.com"):
        values["times"] = previous.times
        date_node = page.by_class("date")
        raw_date = date_node.text().strip() if date_node else ""
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_date):
            try:
                on = date.fromisoformat(raw_date)
            except ValueError:
                on = None
            if on and date(1970, 1, 1) <= on <= now.date() + timedelta(days=1):
                values["times"] = publication_times(
                    previous.times,
                    ContentTime(
                        kind="original",
                        precision="date",
                        on=on,
                        raw=raw_date,
                        basis="fortune:visible-date",
                    ),
                )
    if host == "news.cn" or host.endswith(".news.cn"):
        values["times"] = previous.times
        raw_date = page.meta("publishdate")
        if raw_date and re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_date):
            try:
                published = date.fromisoformat(raw_date)
            except ValueError:
                published = None
            source_name = page.meta("source") or ""
            kind: Literal["original", "reprint"] = (
                "reprint" if source_name and "\u65b0\u534e" not in source_name else "original"
            )
            if published and date(1970, 1, 1) <= published <= now.date() + timedelta(days=1):
                values["times"] = publication_times(
                    previous.times,
                    ContentTime(
                        kind=kind,
                        precision="date",
                        on=published,
                        raw=raw_date,
                        basis="xinhua:meta:publishdate",
                    ),
                )
        body = page.by_id("detailContent")
        if body:
            match = re.match(
                r"^\s*\u65b0\u534e\u793e[^。]{0,80}\u7535[（(]\u8bb0\u8005([^）)]+)[）)]",
                body.text(),
            )
            if match:
                values["authors"] = previous.authors + tuple(
                    Author(
                        name=name,
                        role="reporter",
                        platform=previous.platform,
                        basis="xinhua:visible-wire-byline",
                    )
                    for name in re.split(r"[、，,\s]+", match[1])
                    if name
                    and not any(
                        author.name == name and author.role == "reporter"
                        for author in previous.authors
                    )
                )
    media: tuple[str, str] | None = None
    for node in page.nodes:
        if node.excluded:
            continue
        known_xinhua = host == "news.cn" or host.endswith(".news.cn")
        declared_media = previous.form in {"video", "audio"} or (
            page.meta("og:type") or ""
        ).startswith(("video", "music"))
        value = (node.attrs.get("video_src") if known_xinhua else None) or (
            node.attrs.get("src") if node.tag in {"video", "audio"} and declared_media else None
        )
        if value:
            media = ("audio" if node.tag == "audio" else "video", urljoin(url, value))
            break
    if media is None:
        value = page.meta("og:video") or page.meta("og:video:url") or page.meta("og:audio")
        if value:
            media = ("audio" if page.meta("og:audio") else "video", urljoin(url, value))
    if media:
        try:
            values["media_url"] = public_url(media[1])
            values["form"] = media[0]
        except ValueError:
            pass
    elif host in {"www.bbc.co.uk", "www.bbc.com", "bbc.co.uk", "bbc.com"}:
        # BBC's primary VideoObject has no og:video or HTML video element.
        # Use its page-declared type, never a URL suffix or an embedded advert.
        documents: list[dict[str, Any]] = []
        for raw in re.findall(
            r"<script\b[^>]*\btype=[\"\x27]application/ld\+json[\"\x27][^>]*>(.*?)</script>",
            html,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            try:
                document = json.loads(raw)
            except ValueError:
                continue
            if isinstance(document, dict):
                documents.append(cast(dict[str, Any], document))
        if len(documents) == 1 and documents[0].get("@type") == "VideoObject":
            values["form"] = "video"
    return ContentMetadata.model_validate(values)


def _body(page: TextPage, html: str, url: str) -> tuple[str, str]:
    host = urlsplit(url).hostname or ""
    node, basis = None, "generic:trafilatura"
    if host == "news.cn" or host.endswith(".news.cn"):
        node, basis = page.by_id("detailContent"), "xinhua:#detailContent"
    elif host == "people.com.cn" or host.endswith(".people.com.cn"):
        node, basis = page.by_id("ozoom"), "people:#ozoom"
    elif host == "bjnews.com.cn" or host.endswith(".bjnews.com.cn"):
        node, basis = page.by_class("content-name"), "bjnews:.content-name"
        for candidate in page.nodes:
            if candidate.attrs.get("label") == "\u56fe\u7247\u8bf4\u660e":
                candidate.excluded = True
    elif host == "book.douban.com":
        node, basis = page.by_class("review-content"), "douban:.review-content"
    elif host == "fortunechina.com" or host.endswith(".fortunechina.com"):
        node = page.by_class("word-zh") or page.by_class("word-cn")
        basis = "fortune:chinese-body"
        for candidate in page.nodes:
            if candidate.tag == "font" and candidate.attrs.get("color", "").lower() == "gray":
                candidate.excluded = True
    if node is not None:
        return node.text(), basis
    # A missing known container must not promote a navigation/template shell.
    if basis != "generic:trafilatura":
        return "", basis + ":missing"
    return extract_content(page.root.markup(), url) or "", basis


def _clean_body(text: str, url: str) -> tuple[list[str], list[str]]:
    removed: list[str] = []
    host = urlsplit(url).hostname or ""
    if any(host == domain or host.endswith("." + domain) for domain in ("qq.com", "163.com")):
        # Verified R0 C21/C41 boundary: preserve the exact trailing CCTV credits
        # separately. Do not discard arbitrary similar paragraphs or overlap.
        match = re.search(
            r"(\u603b\u76d1\u5236[\u4e28｜][\s\S]{10,500}©20\d\d"
            r"\u4e2d\u592e\u5e7f\u64ad\u7535\u89c6\u603b\u53f0"
            r"\u7248\u6743\u6240\u6709。\u672a\u7ecf\u8bb8\u53ef，"
            r"\u8bf7\u52ff\u8f6c\u8f7d\u4f7f\u7528。)\s*$",
            text,
        )
        if match:
            removed, text = paragraphs(match[1]), text[: match.start()]
    return paragraphs(text), removed


def body_identity(text: str) -> str:
    value = " ".join(unicodedata.normalize("NFKC", text).split())
    # Chinese paragraph/line wrapping is not a new body; keep Latin word and
    # numeric boundaries rather than deleting all whitespace indiscriminately.
    value = re.sub(r"(?<=[\u3400-\u9fff。，！？；：、）”’]) +(?=[\u3400-\u9fff0-9（“‘])", "", value)
    return re.sub(r"(?<=[0-9]) +(?=[\u3400-\u9fff])", "", value)


def retrieve_material(
    source: Source, payload: dict[str, Any], client: httpx.Client, *, now: datetime | None = None
) -> MaterialResult:
    config = source.r1
    if config is None:
        raise ValueError("R1 material capability is not declared")
    now = now or datetime.now(UTC)
    if config.adapter == "zhihu_daily":
        from unspun.pipeline.editions import retrieve_daily

        return retrieve_daily(source, payload, client, now=now)
    metadata_raw = dict(payload["metadata"])
    title = str(metadata_raw.pop("title"))
    metadata = ContentMetadata.model_validate(metadata_raw)
    url = str(payload["url"])
    provided = str(payload.get("provided_text") or "")
    excerpt = payload.get("source_excerpt")
    status: int | None = None
    response_fp: str | None = None
    access: Literal["ok", "restricted", "unavailable", "failed"] = "ok"
    scope, basis, text_body = config.material_scope, "feed:provided", ""
    evidence: dict[str, Any] = {
        "source_id": source.id,
        "extractor_version": MATERIAL_VERSION,
        "feed_text_truncated": bool(payload.get("provided_truncated")),
    }
    # A self-contained feed brief or declared preview is the actual material
    # unit. Never fetch a paywall merely to pretend this unit is a full article.
    direct = config.material_scope in {
        "complete_brief",
        "preview",
        "question_background",
        "media_description",
    } and bool(provided)
    if direct:
        text_body = provided
        evidence["origin_requested"] = False
    else:
        try:
            response = get_page(client, url, source)
            status, url = response.status_code, str(response.url)
            response_fp = hashlib.sha256(response.content).hexdigest()
            if status in {401, 403, 429}:
                access = "restricted"
            elif status >= 400:
                access = "unavailable"
            elif urlsplit(url).hostname == "sec.douban.com":
                # The 200 security redirect is not review text. Its extracted
                # body can contain only the spaced logo and no captcha words.
                # Never let its template metadata replace article provenance.
                access, basis = "restricted", "origin:douban-security-redirect"
                evidence["security_redirect"] = True
            elif 200 <= status < 300:
                page = TextPage(response.text)
                if config.adapter in {"thepaper", "netease", "tencent"}:
                    from unspun.pipeline.public_sources import PAPER_BYLINE_VERSION, public_material

                    metadata, text_body, basis = public_material(
                        page, response.text, url, metadata, now
                    )
                    if config.adapter == "thepaper":
                        evidence["attribution_version"] = PAPER_BYLINE_VERSION
                else:
                    metadata = _metadata(page, response.text, url, now, metadata)
                    text_body, basis = _body(page, response.text, url)
                lower = " ".join(text_body.split()).lower()
                challenge = any(
                    token in lower
                    for token in (
                        "verify you are human",
                        "just a moment",
                        "captcha",
                        "\u5b89\u5168\u9a8c\u8bc1",
                        "\u8bf7\u5b8c\u6210\u9a8c\u8bc1",
                        "\u9a8c\u8bc1\u7801",
                    )
                )
                if challenge and len(text_body) < 1000:
                    text_body, access = "", "restricted"
                if not text_body:
                    access = "unavailable" if access == "ok" else access
        except (httpx.HTTPError, ValueError) as error:
            access = "failed"
            evidence["error_kind"] = type(error).__name__
        if not text_body and provided:
            text_body, scope, basis = provided, "feed_lead", "feed:fallback_after_origin"
    if metadata.form in {"video", "audio"}:
        scope = "media_description"
    if payload.get("provided_truncated") and basis.startswith("feed:"):
        scope = "feed_lead"
    units, removed = _clean_body(text_body, url)
    if (
        metadata.form in {"video", "audio"}
        and metadata.platform == "xinhua"
        and units
        and all(
            re.fullmatch(
                r"(?:\u8bb0\u8005|\u7f16\u5bfc|\u7f16\u8f91|\u5236\u4f5c)[\uff1a:]"
                r"\s*[\u3400-\u9fff]{2,4}"
                r"(?:[\u3001\uff0c,\s]+[\u3400-\u9fff]{2,4})*\s*"
                r"|\u65b0\u534e\u793e[\u3400-\u9fff]{0,30}(?:\u5236\u4f5c|\u51fa\u54c1)",
                unit.strip(),
            )
            for unit in units
        )
    ):
        evidence["media_credits_only"] = units
        units = ()
    if removed:
        evidence["trailing_credits"] = removed
    if metadata.form == "question":
        scope = "question_background"
    if not units:
        scope = "none"
        if access == "ok":
            access = "unavailable"
    completeness: Literal["observed_unit", "partial", "none", "unknown"] = (
        "none"
        if not units
        else "partial"
        if scope in {"preview", "feed_lead", "media_description", "question_background"}
        else "observed_unit"
    )
    if scope == "open_text_unit" and basis == "generic:trafilatura":
        completeness = "unknown"
    return MaterialResult(
        scope=scope,
        access_status=access,
        completeness=completeness,
        basis=basis,
        source_url=url,
        retrieved_at=now,
        response_status=status,
        response_fingerprint=response_fp,
        paragraphs=tuple(Paragraph(text=value) for value in units),
        source_excerpt=cast(str | None, excerpt),
        metadata=metadata,
        title=title,
        evidence=evidence,
    )


def invalidate_derivations(session: Session, article_id: int, reason: str) -> None:
    session.execute(
        update(ContentDerivation)
        .where(
            ContentDerivation.article_id == article_id, ContentDerivation.status != "invalidated"
        )
        .values(status="invalidated", reason=reason)
    )


def canonical_root(session: Session, article_id: int) -> int:
    seen: set[int] = set()
    while article_id not in seen and len(seen) < 64:
        seen.add(article_id)
        article = session.get(Article, article_id)
        if article is None or article.processing_track != "r1":
            raise ValueError("canonical content identity is missing")
        if article.canonical_content_id is None:
            return article.id
        article_id = article.canonical_content_id
    raise ValueError("canonical content relation is cyclic or too deep")


def apply_material(session: Session, lease: Lease, result: MaterialResult) -> dict[str, Any]:
    if lease.article_id is None:
        raise ValueError("material task requires content identity")
    semantic_text = "\n".join(unit.text for unit in result.paragraphs)
    text_fp = fingerprint(body_identity(semantic_text)) if semantic_text else None
    metadata = {"title": result.title, **result.metadata.model_dump(mode="json")}
    metadata_fp = fingerprint(metadata)
    input_fp = fingerprint(
        [
            MATERIAL_VERSION,
            result.scope,
            result.access_status,
            result.completeness,
            body_identity(semantic_text),
            metadata,
        ]
    )
    # Canonical graph updates are one short serialized DB section. Network
    # requests remain parallel and hold neither this lock nor a DB transaction.
    lock_identity(session, "r1:material-identity")
    article = session.get(Article, lease.article_id, with_for_update=True)
    if article is None or article.processing_track != "r1":
        raise ValueError("material task cannot mutate legacy history")
    current_discovery = observation_version(
        latest_observation(session, article.id, article.source_id)
    )
    current_observation = observation_version(
        latest_observation(session, article.id, lease.source_id or "")
    )
    if (
        lease.payload.get("discovery_version") != current_discovery
        or lease.payload.get("observation_version") != current_observation
    ):
        return {
            "article_id": article.id,
            "material_id": article.current_material_id,
            "stale_metadata": True,
        }
    if lease.source_id != article.source_id and article.r1_metadata:
        primary = dict(article.r1_metadata)
        primary_title = str(primary.pop("title"))
        observed = ContentMetadata.model_validate(primary)
        changes: dict[str, Any] = {}
        if not observed.authors:
            changes["authors"] = tuple(
                author for author in result.metadata.authors if author.basis.startswith("page:")
            )
        if not any(value.kind == "original" for value in observed.times):
            changes["times"] = observed.times + tuple(
                value for value in result.metadata.times if value.kind == "original"
            )
        if result.metadata.media_url:
            changes.update(media_url=result.metadata.media_url, form=result.metadata.form)
        metadata = {
            "title": primary_title,
            **observed.model_copy(update=changes).model_dump(mode="json"),
        }
        metadata_fp = fingerprint(metadata)
        input_fp = fingerprint(
            [
                MATERIAL_VERSION,
                result.scope,
                result.access_status,
                result.completeness,
                body_identity(semantic_text),
                metadata,
            ]
        )
    previous_material = (
        session.get(ContentMaterial, article.current_material_id)
        if article.current_material_id
        else None
    )
    material = session.scalar(
        select(ContentMaterial).where(
            ContentMaterial.article_id == article.id, ContentMaterial.input_fingerprint == input_fp
        )
    )
    canonical: int | None = None
    if (
        text_fp
        and len(semantic_text) >= 80
        and result.scope not in {"feed_lead", "media_description", "none", "question_background"}
    ):
        duplicate = session.scalar(
            select(ContentMaterial)
            .join(Article, Article.id == ContentMaterial.article_id)
            .where(
                ContentMaterial.text_fingerprint == text_fp,
                ContentMaterial.scope == result.scope,
                Article.processing_track == "r1",
                Article.canonical_content_id.is_(None),
                Article.current_material_id == ContentMaterial.id,
                Article.id != article.id,
            )
            .order_by(ContentMaterial.id)
            .limit(1)
        )
        if duplicate:
            canonical = duplicate.article_id
    if material is None:
        material = ContentMaterial(
            article_id=article.id,
            input_fingerprint=input_fp,
            text_fingerprint=text_fp,
            metadata_fingerprint=metadata_fp,
            extractor_version=MATERIAL_VERSION,
            schema_version="r1-material-schema-v1",
            scope=result.scope,
            access_status=result.access_status,
            completeness=result.completeness,
            completeness_basis=result.basis,
            source_url=result.source_url,
            retrieved_at=result.retrieved_at,
            response_status=result.response_status,
            response_fingerprint=result.response_fingerprint,
            paragraphs=[unit.model_dump() for unit in result.paragraphs],
            source_excerpt=result.source_excerpt,
            evidence=result.evidence,
        )
        session.add(material)
        session.flush()
    scope_rank = {
        "none": 0,
        "feed_lead": 1,
        "preview": 2,
        "question_background": 2,
        "media_description": 2,
        "complete_brief": 3,
        "editorial_edition": 4,
        "open_text_unit": 4,
    }
    if (
        previous_material
        and previous_material.metadata_fingerprint == metadata_fp
        and metadata.get("form") == article.content_form
        and scope_rank.get(previous_material.scope, 0) > scope_rank.get(material.scope, 0)
    ):
        # Keep the last observed material with its original retrieval time. The
        # failed/restricted new version remains visible in the material history.
        return {
            "article_id": article.id,
            "material_id": previous_material.id,
            "observed_material_id": material.id,
            "scope": previous_material.scope,
            "observed_scope": material.scope,
            "access_status": material.access_status,
            "retained_previous_material": True,
            "canonical_content_id": article.canonical_content_id,
        }
    if (
        article.current_material_id != material.id
        or article.metadata_fingerprint != metadata_fp
        or article.canonical_content_id != canonical
    ):
        invalidate_derivations(session, article.id, "material_or_metadata_changed")
    if previous_material and previous_material.text_fingerprint != text_fp:
        dependents = list(
            session.scalars(
                select(Article)
                .where(Article.canonical_content_id == article.id)
                .order_by(Article.id)
                .with_for_update()
            )
        )
        groups: dict[tuple[str, str], list[Article]] = {}
        for dependent in dependents:
            observed = (
                session.get(ContentMaterial, dependent.current_material_id)
                if dependent.current_material_id
                else None
            )
            if observed and observed.text_fingerprint:
                groups.setdefault((observed.scope, observed.text_fingerprint), []).append(dependent)
            else:
                dependent.canonical_content_id = None
            invalidate_derivations(session, dependent.id, "canonical_material_changed")
        for (old_scope, old_fingerprint), members in groups.items():
            if (old_scope, old_fingerprint) == (result.scope, text_fp):
                root = canonical or article.id
            else:
                existing_root = session.scalar(
                    select(Article.id)
                    .join(ContentMaterial, ContentMaterial.id == Article.current_material_id)
                    .where(
                        Article.id != article.id,
                        Article.processing_track == "r1",
                        Article.id.not_in([member.id for member in members]),
                        Article.canonical_content_id.is_(None),
                        ContentMaterial.scope == old_scope,
                        ContentMaterial.text_fingerprint == old_fingerprint,
                    )
                    .order_by(Article.id)
                    .limit(1)
                )
                root = existing_root or members[0].id
            for member in members:
                member.canonical_content_id = None if member.id == root else root
    article.current_material_id = material.id
    article.canonical_content_id = canonical
    # Preserve primary channel values; separately verified page fields may fill
    # missing canonical metadata without promoting alternate feed labels.
    article.title, article.r1_metadata, article.metadata_fingerprint = (
        str(metadata["title"]),
        metadata,
        metadata_fp,
    )
    article.content_form = str(metadata["form"])
    article.platform = metadata.get("platform")
    article.publisher_name = metadata.get("publisher")
    alias = session.scalar(select(ContentUrl).where(ContentUrl.url == result.source_url))
    if alias is None and result.source_url != article.url:
        session.add(ContentUrl(article_id=article.id, url=result.source_url, relation="redirect"))
    elif (
        alias is not None
        and alias.article_id != article.id
        and canonical_root(session, alias.article_id) != (canonical or article.id)
    ):
        raise ValueError("redirect alias belongs to another canonical object")
    return {
        "article_id": article.id,
        "material_id": material.id,
        "scope": material.scope,
        "access_status": material.access_status,
        "canonical_content_id": canonical,
    }


class MaterialHandler:
    def __init__(self, sources: dict[str, Source]) -> None:
        self.sources = sources

    def run(self, lease: Lease) -> MaterialResult:
        source = self.sources[lease.source_id or ""]
        if source.r1 is None or not source.r1.material:
            raise ValueError("R1 material stage is disabled")
        with make_client() as client:
            result = retrieve_material(source, lease.payload, client)
        if result.access_status == "failed" or (
            result.response_status is not None and result.response_status >= 500
        ):
            raise RuntimeError("material retrieval requires bounded retry")
        return result

    def apply(self, session: Session, lease: Lease, result: MaterialResult) -> dict[str, Any]:
        batch_id = lease.payload.get("quota_batch_id")
        if batch_id is not None:
            from unspun.pipeline.discovery_quotas import selection_lock

            selection_lock(session)
        applied = apply_material(session, lease, result)
        source = self.sources[lease.source_id or ""]
        current = (
            session.get(ContentMaterial, int(applied["material_id"]))
            if applied.get("material_id") is not None
            else None
        )
        if batch_id is not None and current and not applied.get("stale_metadata"):
            from unspun.pipeline.discovery_quotas import select_processing

            batch = session.get(DiscoveryBatch, int(batch_id))
            if batch is None or lease.task_id not in batch.material_tasks:
                raise ValueError("material task has no matching quota receipt")
            outcome = select_processing(session, source, batch, int(applied["article_id"]))
            applied["card_enqueue_reason"] = outcome["reason"]
            if "task_id" in outcome:
                applied["card_task_id"] = outcome["task_id"]
            return applied
        if (
            source.r1
            and current
            and source.r1.allows_paid(current.scope)
            and not applied.get("stale_metadata")
        ):
            from unspun.pipeline.content_processing import enqueue_processing

            applied["card_task_id"] = enqueue_processing(session, int(applied["article_id"]))
        elif source.r1 and source.r1.paid and current and not applied.get("stale_metadata"):
            applied["card_enqueue_reason"] = "paid_material_scope_disabled"
        return applied
