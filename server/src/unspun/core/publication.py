"""Conservative original-publication provenance from untrusted primary-page HTML."""

import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from html.parser import HTMLParser
from typing import Literal, cast
from urllib.parse import unquote_plus, urljoin, urlsplit, urlunsplit

_MAX_HTML_BYTES = 2 * 1024 * 1024
_MAX_JSON_DEPTH = 32
_MAX_JSON_NODES = 10_000
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_SKEW = timedelta(minutes=5)
_ARTICLE_TYPES = {"Article", "NewsArticle", "BlogPosting", "ScholarlyArticle"}
_TRACKING = {"fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid"}
_ISO = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?:[Tt ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?"
    r"(?:[Zz]|[+-]\d{2}:\d{2})?)?$"
)


@dataclass(frozen=True)
class PublicationTime:
    reported_at: datetime | None = None
    reported_date: date | None = None
    precision: Literal["time", "date", "unknown"] = "unknown"
    basis: str = "none"
    status: str = "missing"


def publication_bounds(
    reported_at: datetime | None,
    reported_date: date | None,
    fetched_at: datetime,
    as_of: datetime,
) -> tuple[datetime, datetime] | None:
    """Return ordering uncertainty bounds; a date's lower bound is not publication time.

    All supplied datetimes must be timezone-aware. Date-only observations span
    UTC+14 through UTC-12 and are capped by both observation and evaluation time.
    """
    if fetched_at.utcoffset() is None or as_of.utcoffset() is None:
        return None
    try:
        ceiling = min(fetched_at.astimezone(UTC) + _SKEW, as_of.astimezone(UTC))
        if reported_at is not None:
            if reported_at.utcoffset() is None:
                return None
            instant = reported_at.astimezone(UTC)
            return (instant, instant) if _EPOCH <= instant <= ceiling else None
        if reported_date is None or reported_date < _EPOCH.date():
            return None
        midnight = datetime.combine(reported_date, time(), tzinfo=UTC)
        lower = max(midnight - timedelta(hours=14), _EPOCH)
        upper = min(midnight + timedelta(days=1, hours=12), ceiling)
        return (lower, upper) if lower <= upper else None
    except (ValueError, OverflowError):
        return None


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.metadata: list[tuple[str, str]] = []
        self.canonicals: list[str] = []
        self.blocks: list[str] = []
        self._script: list[str] | None = None
        self.history: list[str] = []
        self._history_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "meta":
            name = (attributes.get("property") or attributes.get("name") or "").lower()
            value = attributes.get("content")
            if name in {"article:published_time", "datepublished"} and value:
                self.metadata.append(("meta:" + name, value))
        if tag == "link" and "canonical" in (attributes.get("rel") or "").lower().split():
            href = attributes.get("href")
            if href:
                self.canonicals.append(href)
        if tag == "script" and (
            (attributes.get("type") or "").lower().split(";")[0].strip() == "application/ld+json"
        ):
            self._script = []
        if tag == "div":
            if self._history_depth:
                self._history_depth += 1
            elif "submission-history" in (attributes.get("class") or "").split():
                self._history_depth = 1
        if self._history_depth:
            self.history.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._script is not None:
            self.blocks.append("".join(self._script))
            self._script = None
        if tag == "div" and self._history_depth:
            self._history_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._script is not None:
            self._script.append(data)
        if self._history_depth:
            self.history.append(data)


def _identity(value: str, base: str) -> str | None:
    try:
        parts = urlsplit(urljoin(base, value))
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username:
            return None
        query: list[str] = []
        for part in parts.query.split("&"):
            key = unquote_plus(part.partition("=")[0]).lower()
            if not key.startswith("utm_") and key not in _TRACKING:
                query.append(part)
        return urlunsplit(
            (parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", "&".join(query), "")
        )
    except ValueError:
        return None


@dataclass
class _RepeatedPublicationValues:
    values: list[object]


class _JsonObjectHook:
    def __init__(self) -> None:
        self.remaining_nodes = _MAX_JSON_NODES

    def __call__(self, pairs: list[tuple[str, object]]) -> dict[str, object]:
        # Count source values before duplicate keys could collapse them in a dict.
        self.remaining_nodes -= len(pairs) + 1
        if self.remaining_nodes < 0:
            raise ValueError("JSON object node budget exceeded")
        mapping: dict[str, object] = {}
        for key, value in pairs:
            if key not in mapping:
                mapping[key] = value
                continue
            if key != "datePublished":
                raise ValueError("ambiguous duplicate JSON key")
            previous = mapping[key]
            if isinstance(previous, _RepeatedPublicationValues):
                previous.values.append(value)
            else:
                mapping[key] = _RepeatedPublicationValues([previous, value])
        return mapping


def _json_articles(block: str) -> list[dict[str, object]]:
    # Bound nesting before json.loads, including quoted/escaped braces correctly.
    depth = 0
    quoted = escaped = False
    for char in block:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > _MAX_JSON_DEPTH:
                return []
        elif char in "]}":
            depth -= 1
    try:
        root = cast(object, json.loads(block, object_pairs_hook=_JsonObjectHook()))
    except (ValueError, RecursionError):
        return []
    pending: list[object] = [root]
    articles: list[dict[str, object]] = []
    visited = 0
    while pending:
        visited += 1
        if visited > _MAX_JSON_NODES:
            return []
        node = pending.pop()
        if isinstance(node, dict):
            mapping = cast(dict[str, object], node)
            kind = mapping.get("@type")
            kinds = cast(list[object], kind) if isinstance(kind, list) else [kind]
            if any(isinstance(k, str) and k.rsplit("/", 1)[-1] in _ARTICLE_TYPES for k in kinds):
                articles.append(mapping)
            pending.extend(mapping.values())
        elif isinstance(node, list):
            pending.extend(cast(list[object], node))
    return articles


def _article_identities(article: dict[str, object]) -> list[str]:
    identities: list[str] = []
    for key in ("url", "@id", "mainEntityOfPage"):
        value = article.get(key)
        if isinstance(value, dict):
            value = cast(dict[str, object], value).get("@id")
        if isinstance(value, str):
            identities.append(value)
    return identities


def _parse(value: str, basis: str, fetched_at: datetime) -> PublicationTime | None:
    value = value.strip()
    if not _ISO.fullmatch(value):
        return None
    try:
        if len(value) == 10:
            observed = date.fromisoformat(value)
            instant = None
        else:
            parsed = datetime.fromisoformat(value.replace("z", "+00:00").replace("Z", "+00:00"))
            observed = parsed.date()
            instant = parsed.astimezone(UTC) if parsed.utcoffset() is not None else None
        if publication_bounds(instant, observed, fetched_at, fetched_at + _SKEW) is None:
            return None
        return PublicationTime(instant, observed, "time" if instant else "date", basis, "ok")
    except (ValueError, OverflowError):
        return None


def _arxiv(page: _PageParser, fetched_at: datetime) -> PublicationTime:
    history = " ".join(page.history)
    matches = re.findall(
        r"\[v1\]\s*([A-Za-z]{3},\s*\d{1,2}\s+[A-Za-z]{3}\s+\d{4}"
        r"\s+\d{2}:\d{2}:\d{2}\s+UTC)(?=$|\s|\()",
        history,
    )
    if len(matches) != 1 or history.count("[v1]") != 1:
        return PublicationTime()
    try:
        instant = datetime.strptime(matches[0], "%a, %d %b %Y %H:%M:%S UTC").replace(tzinfo=UTC)
    except ValueError:
        return PublicationTime(status="invalid")
    return _parse(instant.isoformat(), "arxiv:submission-history:v1", fetched_at) or (
        PublicationTime(status="invalid")
    )


def extract_publication(html: str, url: str, fetched_at: datetime) -> PublicationTime:
    """Extract original publication without inferring timezones or using update dates.

    JSON-LD must identify this page (or its single declared canonical URL).
    arXiv pages use only the unambiguous v1 submission-history entry.
    Oversize input and malformed blocks are never evaluated or fetched.
    """
    if len(html) > _MAX_HTML_BYTES or len(html.encode("utf-8", errors="replace")) > _MAX_HTML_BYTES:
        return PublicationTime(status="too_large")
    if fetched_at.utcoffset() is None:
        return PublicationTime(status="invalid")
    page = _PageParser()
    try:
        page.feed(html)
        page.close()
    except (ValueError, RecursionError):
        return PublicationTime(status="invalid")
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return PublicationTime(status="invalid")
    if host in {"arxiv.org", "www.arxiv.org", "export.arxiv.org"}:
        return _arxiv(page, fetched_at)
    aliases = {_identity(url, url)}
    canonicals = {_identity(value, url) for value in page.canonicals} - {None}
    if len(canonicals) > 1:
        return PublicationTime(status="conflict")
    if len(canonicals) == 1:
        aliases.update(canonicals)
    aliases.discard(None)
    candidates = list(page.metadata)
    for block in page.blocks:
        for article in _json_articles(block):
            identities = {_identity(value, url) for value in _article_identities(article)}
            identities.discard(None)
            if identities and identities <= aliases:
                value = article.get("datePublished")
                values = value.values if isinstance(value, _RepeatedPublicationValues) else [value]
                for item in values:
                    if isinstance(item, str):
                        candidates.append(("jsonld:datePublished", item))
    parsed = [
        result
        for basis, value in candidates
        if (result := _parse(value, basis, fetched_at)) is not None
    ]
    if len(parsed) != len(candidates):
        return PublicationTime(status="invalid")
    if not parsed:
        return PublicationTime()
    instants = {result.reported_at for result in parsed if result.reported_at is not None}
    dates = {result.reported_date for result in parsed if result.reported_at is None}
    if len(instants) > 1 or len(dates) > 1:
        return PublicationTime(status="conflict")
    precise = next((result for result in parsed if result.reported_at is not None), None)
    if precise and dates and precise.reported_date not in dates:
        return PublicationTime(status="conflict")
    return precise or parsed[0]
