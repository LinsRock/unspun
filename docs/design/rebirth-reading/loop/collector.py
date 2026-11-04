#!/usr/bin/env python3
"""Bounded, local-only public-feed discovery and explicitly selected body retrieval."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import fcntl
import hashlib
import http.client
from html.parser import HTMLParser
import ipaddress
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

SCHEMA_VERSION = 1
RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
SOURCE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
CANDIDATE_ID = re.compile(r"live-[a-f0-9]{24}\Z")
REPOSITORY = Path(__file__).resolve().parents[4]
CACHE_NOTICE = "Cached body reused for unchanged feed metadata; source freshness was not rechecked."


def utc_now():
    return datetime.now(timezone.utc)


def iso_now():
    return utc_now().isoformat()


def atomic_bytes(path, data):
    """Replace only a complete file, syncing both its bytes and directory entry."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_json(path, value):
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())


def validate_state_dir(path):
    path = Path(path).expanduser().resolve()
    if path == REPOSITORY or REPOSITORY in path.parents:
        raise ValueError("state-dir must be outside the repository; raw source text stays local")
    path.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def writer_lock(state_dir):
    """An OS lock releases on crashes; never unlink the lock inode while in use."""
    lock_path = Path(state_dir) / ".collector.lock"
    with lock_path.open("a+", encoding="utf-8") as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError(f"another collector holds {lock_path}") from error
        try:
            stream.seek(0)
            stream.truncate()
            json.dump({"pid": os.getpid(), "acquiredAt": iso_now()}, stream)
            stream.flush()
            os.fsync(stream.fileno())
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def normalize_url(url, base=None):
    if not isinstance(url, str) or not url.strip():
        raise ValueError("URL must be a nonempty string")
    url = urllib.parse.urljoin(base, url.strip()) if base else url.strip()
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme.lower() not in {"https", "http"} or not parsed.hostname:
        raise ValueError("only absolute public HTTP(S) URLs are allowed")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URL credentials are forbidden")
    if any(ord(character) < 32 for character in url):
        raise ValueError("URL contains control characters")
    host = parsed.hostname.encode("idna").decode().lower().rstrip(".")
    port = parsed.port
    if port not in {None, 80, 443}:
        raise ValueError("nonstandard URL ports are forbidden")
    try:
        address = ipaddress.ip_address(host)
        if not address.is_global:
            raise ValueError("nonpublic IP addresses are forbidden")
    except ValueError as error:
        if "nonpublic" in str(error):
            raise
    if host == "localhost" or host.endswith((".localhost", ".local")):
        raise ValueError("local hosts are forbidden")
    authority = f"[{host}]" if ":" in host else host
    if port and not (parsed.scheme.lower() == "https" and port == 443) and not (
        parsed.scheme.lower() == "http" and port == 80
    ):
        authority += f":{port}"
    # Preserve significant query bytes/order, including signatures and duplicate keys.
    query = "&".join(
        part for part in parsed.query.split("&")
        if not urllib.parse.unquote_plus(part.split("=", 1)[0]).lower().startswith("utm_")
    )
    return urllib.parse.urlunsplit((parsed.scheme.lower(), authority, parsed.path or "/", query, ""))


def allowed_url(url, source):
    normalized = normalize_url(url)
    host = urllib.parse.urlsplit(normalized).hostname
    if host not in source["allowedHosts"]:
        raise ValueError(f"URL host {host} is outside this source's explicit allowlist")
    return normalized


def read_config(path):
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(config, dict) or config.get("schemaVersion") != SCHEMA_VERSION:
        raise ValueError("unsupported source configuration schema")
    sources = config.get("sources")
    if not isinstance(sources, list) or not 1 <= len(sources) <= 12:
        raise ValueError("sources must contain 1–12 entries")
    seen = set()
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get("id"), str) or not SOURCE_ID.fullmatch(source["id"]):
            raise ValueError("invalid source id")
        if source["id"] in seen:
            raise ValueError("duplicate source id")
        seen.add(source["id"])
        for key in ("name", "domain"):
            if not isinstance(source.get(key), str) or not source[key].strip():
                raise ValueError(f"source {key} must be a nonempty string")
        hosts = source.get("allowedHosts")
        if not isinstance(hosts, list) or not hosts or not all(
            isinstance(host, str) and re.fullmatch(r"[a-z0-9.-]+", host)
            and ".." not in host and not host.startswith(".") and not host.endswith(".")
            for host in hosts
        ):
            raise ValueError("allowedHosts must be explicit lowercase host names")
        source["url"] = allowed_url(source.get("url"), source)
        source.setdefault("maxItems", 8)
        if type(source["maxItems"]) is not int or not 1 <= source["maxItems"] <= 8:
            raise ValueError("maxItems must be between 1 and 8")
    limits = config.get("limits", {})
    if not isinstance(limits, dict):
        raise ValueError("limits must be an object")
    for key, default, maximum in (
        ("maxRequests", 24, 24), ("maxBytes", 2_000_000, 2_000_000), ("timeoutSeconds", 10, 30)
    ):
        limits.setdefault(key, default)
        if type(limits[key]) is not int or not 1 <= limits[key] <= maximum:
            raise ValueError(f"invalid bounded limit {key}")
    config["limits"] = limits
    return config


def parse_date(raw):
    """Require an explicit source timezone; never substitute discovery time."""
    if not raw:
        return None
    raw = raw.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})", raw):
            value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        else:
            value = parsedate_to_datetime(raw)
        if value.tzinfo is None or value.utcoffset() is None:
            return None
        return value
    except (TypeError, ValueError, OverflowError):
        return None


def local_name(tag):
    return tag.rsplit("}", 1)[-1]


def child_text(element, *names):
    for name in names:
        for child in element:
            if local_name(child.tag) == name:
                return "".join(child.itertext()).strip() or None
    return None


def metadata_fingerprint(candidate):
    keys = ("url", "title", "author", "publishedAt", "rawPublishedAt")
    value = json.dumps({key: candidate.get(key) for key in keys}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(value.encode()).hexdigest()


def parse_feed(data, source, discovered_at=None, window_days=14):
    discovered_at = discovered_at or utc_now()
    if re.search(br"<!\s*(DOCTYPE|ENTITY)\b", data, re.I):
        raise ValueError("DTD/entity declarations are not accepted")
    root = ET.fromstring(data)
    if local_name(root.tag) not in {"rss", "RDF", "feed"}:
        raise ValueError("response is not an RSS or Atom feed")
    atom = local_name(root.tag) == "feed"
    entries = [entry for entry in root.iter() if local_name(entry.tag) == ("entry" if atom else "item")]
    candidates, rejected, seen = [], [], set()
    for entry in entries:
        if len(candidates) >= source["maxItems"]:
            break
        raw_url = None
        if atom:
            for link in entry:
                if local_name(link.tag) == "link" and link.get("rel", "alternate") == "alternate":
                    raw_url = link.get("href")
                    if raw_url:
                        break
        else:
            raw_url = child_text(entry, "link")
        try:
            url = allowed_url(normalize_url(raw_url, source["url"]), source)
        except (ValueError, TypeError) as error:
            rejected.append({"url": raw_url, "reason": str(error)})
            continue
        if url in seen:
            rejected.append({"url": url, "reason": "duplicate canonical URL"})
            continue
        seen.add(url)
        raw_date = child_text(entry, "published") if atom else child_text(entry, "pubDate", "date")
        published = parse_date(raw_date)
        disposition = "unknown-date"
        date_issue = "missing-or-unparseable-source-publication-date" if not published else None
        if published:
            if published > discovered_at + timedelta(minutes=5):
                disposition, date_issue = "outside-window", "future-source-publication-date"
            else:
                disposition = "recent" if published >= discovered_at - timedelta(days=window_days) else "outside-window"
        author = child_text(entry, "author", "creator")
        if atom:
            author_node = next((child for child in entry if local_name(child.tag) == "author"), None)
            if author_node is not None:
                author = child_text(author_node, "name")
        candidate = {
            "id": "live-" + hashlib.sha256(url.encode()).hexdigest()[:24],
            "sourceId": source["id"], "sourceName": source["name"], "domain": source["domain"],
            "url": url, "title": child_text(entry, "title") or "(untitled)", "author": author,
            "publishedAt": published.isoformat() if published else None, "rawPublishedAt": raw_date,
            "rawUpdatedAt": child_text(entry, "updated") if atom else None,
            "discoveredAt": discovered_at.isoformat(), "disposition": disposition, "dateIssue": date_issue,
            "bodyStatus": "pending", "bodyPath": None, "contentHash": None,
            "materialScope": "metadata", "bodyChars": 0, "bodyCacheReuse": None, "bodyAttempts": [],
        }
        candidate["metadataFingerprint"] = metadata_fingerprint(candidate)
        candidates.append(candidate)
    return candidates, rejected


class ArticleParser(HTMLParser):
    """Explicit article regions are bodies; ambiguous page text is only an excerpt."""
    EXCLUDED = {"script", "style", "nav", "footer", "header", "aside", "noscript", "svg", "form"}
    BLOCKS = {"p", "div", "article", "main", "section", "h1", "h2", "h3", "li", "br", "blockquote"}
    WRAPPERS = {"article-content", "article-body", "article_body", "articlecontent", "entry-content", "post-content", "post-body", "content-body", "post_content"}
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self, source_url=None):
        super().__init__(convert_charrefs=True)
        self.source_host = urllib.parse.urlsplit(source_url or "").hostname
        self.stack = []
        self.all_text = []
        self.regions = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        excluded = tag in self.EXCLUDED or any(frame[1] for frame in self.stack)
        labels = set(re.split(r"\s+", (attrs.get("class") or "").lower())) | {(attrs.get("id") or "").lower()}
        explicit = tag in {"article", "main"} or bool(labels & self.WRAPPERS) or attrs.get("itemprop", "").lower() == "articlebody"
        evidence = tag if tag in {"article", "main"} else "article-content-wrapper"
        # These site-specific boundaries were verified against saved pilot HTML.
        # The generic class "article" alone is not evidence on arbitrary pages.
        if self.source_host == "www.qbitai.com" and tag == "div" and "article" in labels and self.stack and "content" in self.stack[-1][3]:
            explicit, evidence = True, "www.qbitai.com div.content > div.article"
        if self.source_host == "www.solidot.org" and tag == "div" and "p_mainnew" in labels and any("articlebox" in frame[3] for frame in self.stack):
            explicit, evidence = True, "www.solidot.org .articleBox .p_mainnew"
        region = None
        if explicit and not excluded:
            region = {"evidence": evidence, "chunks": []}
            self.regions.append(region)
        if tag in self.BLOCKS and not excluded:
            self.handle_data("\n")
        if tag not in self.VOID:
            self.stack.append((tag, excluded, region, labels))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                if tag in self.BLOCKS:
                    self.handle_data("\n")
                del self.stack[index:]
                break

    def handle_data(self, data):
        if any(frame[1] for frame in self.stack):
            return
        self.all_text.append(data)
        for _, _, region, _ in self.stack:
            if region is not None:
                region["chunks"].append(data)

    @staticmethod
    def clean(chunks):
        lines = [re.sub(r"[\t \r\f\v]+", " ", line).strip() for line in "".join(chunks).split("\n")]
        return "\n\n".join(line for line in lines if line)

    def extract(self):
        regions = [(self.clean(region["chunks"]), region["evidence"]) for region in self.regions]
        text, evidence = max(regions, key=lambda region: len(region[0]), default=("", None))
        if len(text) >= 80:
            return text, "body", evidence
        text = self.clean(self.all_text)[:2000]
        if len(text) < 80:
            raise ValueError("no readable article body or meaningful page excerpt")
        return text, "excerpt", "generic-page-text; article boundaries not established"


def extract_body(data, content_type, source_url=None):
    charset = re.search(r"charset\s*=\s*[\"']?([\w-]+)", content_type or "", re.I)
    if not charset:
        charset = re.search(br"charset\s*=\s*[\"']?([\w-]+)", data[:4096], re.I)
    encoding = charset.group(1) if charset else "utf-8"
    if isinstance(encoding, bytes):
        encoding = encoding.decode("ascii")
    try:
        text = data.decode(encoding, errors="replace")
    except LookupError as error:
        raise ValueError("unknown response character encoding") from error
    if "html" not in (content_type or "").lower() and not re.search(r"<(?:html|article|main|div)\b", text[:4096], re.I):
        raise ValueError("body response is not HTML; no article extraction attempted")
    parser = ArticleParser(source_url)
    parser.feed(text)
    parser.close()
    return parser.extract()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


class FetchFailure(Exception):
    def __init__(self, outcome):
        super().__init__(outcome["error"])
        self.outcome = outcome


class Fetcher:
    def __init__(self, limits, usage, opener=None, checkpoint=None):
        self.limits = limits
        self.usage = usage
        self.opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        self.checkpoint = checkpoint or (lambda: None)

    def fetch(self, url, source):
        outcome = {"requestedUrl": url, "finalUrl": None, "httpStatus": None, "redirects": [], "downloadedBytes": 0, "contentType": None}
        try:
            current = allowed_url(url, source)
            for redirect_count in range(5):
                if self.usage["requestCount"] >= self.limits["maxRequests"]:
                    raise ValueError("run-wide request limit reached")
                self.usage["requestCount"] += 1
                # Reserve durably before I/O, so a crash cannot silently refund a request.
                self.checkpoint()
                deadline = time.monotonic() + self.limits["timeoutSeconds"]
                request = urllib.request.Request(current, headers={"User-Agent": "Unspun-Local-Pilot/1.0", "Accept-Encoding": "identity", "Accept": "application/rss+xml, application/atom+xml, application/xml, text/html;q=0.9, */*;q=0.1"})
                response = None
                try:
                    response = self.opener.open(request, timeout=self.limits["timeoutSeconds"])
                except urllib.error.HTTPError as error:
                    response = error
                with response:
                    status = response.status
                    outcome.update(finalUrl=current, httpStatus=status, contentType=response.headers.get("Content-Type", ""))
                    if status in {301, 302, 303, 307, 308}:
                        location = response.headers.get("Location")
                        if not location:
                            raise ValueError("redirect has no Location")
                        destination = allowed_url(urllib.parse.urljoin(current, location), source)
                        outcome["redirects"].append({"from": current, "to": destination, "status": status})
                        if redirect_count == 4:
                            raise ValueError("redirect limit reached")
                        current = destination
                        continue
                    if not 200 <= status < 300:
                        raise ValueError(f"HTTP {status}")
                    encoding = response.headers.get("Content-Encoding", "identity").lower()
                    if encoding not in {"", "identity"}:
                        raise ValueError(f"unexpected compressed response ({encoding}); identity was requested")
                    chunks = []
                    reader = getattr(response, "read1", response.read)
                    while True:
                        if time.monotonic() > deadline:
                            raise TimeoutError("response exceeded its wall-clock time limit")
                        remaining = self.limits["maxBytes"] + 1 - outcome["downloadedBytes"]
                        chunk = reader(min(65536, remaining))
                        outcome["downloadedBytes"] += len(chunk)
                        self.usage["bytesDownloaded"] += len(chunk)
                        if outcome["downloadedBytes"] > self.limits["maxBytes"]:
                            raise ValueError("response exceeds per-response byte limit")
                        if time.monotonic() > deadline:
                            raise TimeoutError("response exceeded its wall-clock time limit")
                        if not chunk:
                            break
                        chunks.append(chunk)
                    data = b"".join(chunks)
                    outcome["status"] = "ok"
                    return data, outcome
            raise ValueError("redirect limit reached")
        except (ValueError, OSError, urllib.error.URLError, http.client.HTTPException) as error:
            outcome.update(status="failed", error=str(error), errorType=type(error).__name__)
            raise FetchFailure(outcome) from error


def state_path(state, relative):
    result = (state / relative).resolve()
    if state not in result.parents:
        raise ValueError("material path escapes state directory")
    return result


def use_cache(state, candidate):
    path = state / "materials" / candidate["id"] / "metadata.json"
    if not path.exists():
        return False
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if cached["metadataFingerprint"] != candidate["metadataFingerprint"]:
            return False
        text = state_path(state, cached["bodyPath"]).read_bytes()
        if hashlib.sha256(text).hexdigest() != cached["contentHash"]:
            return False
        for key in ("bodyPath", "contentHash", "materialScope", "bodyChars", "extractionEvidence", "bodyFetchedAt"):
            candidate[key] = cached[key]
        candidate.update(bodyStatus="readable", bodyCacheReuse={"reusedAt": iso_now(), "notice": CACHE_NOTICE})
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def load_manifest(state, run_id, config):
    if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
        raise ValueError("run-id must be 1–64 safe letters, digits, dots, underscores or hyphens")
    path = state / "runs" / run_id / "manifest.json"
    config_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    if path.exists():
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest.get("runId") != run_id or manifest.get("schemaVersion") != SCHEMA_VERSION:
            raise ValueError("existing run manifest identity/schema mismatch")
        if manifest.get("sourcesConfigHash") != config_hash:
            raise ValueError("source configuration changed; use a new run-id to preserve the original run")
        return manifest, path
    now = iso_now()
    return {"schemaVersion": SCHEMA_VERSION, "runId": run_id, "startedAt": now, "updatedAt": now,
            "sourcesConfigHash": config_hash, "limits": config["limits"], "sources": [], "candidates": [],
            "usage": {"requestCount": 0, "bytesDownloaded": 0, "elapsedMs": 0, "modelCalls": 0, "modelCost": None},
            "phases": []}, path


def collect(config, state, manifest, phase, fetcher, window_days):
    phase["windowDays"] = window_days
    existing = {candidate["id"]: candidate for candidate in manifest["candidates"]}
    for source in config["sources"]:
        outcome = {"phaseId": phase["id"], "sourceId": source["id"], "sourceName": source["name"], "url": source["url"], "attemptedAt": iso_now(), "status": "running"}
        manifest["sources"].append(outcome)
        phase["checkpoint"]()
        try:
            data, response = fetcher.fetch(source["url"], source)
            outcome.update(response)
            raw_path = f"runs/{manifest['runId']}/raw/{phase['id']}/{source['id']}.xml"
            atomic_bytes(state / raw_path, data)
            outcome["rawPath"] = raw_path
            candidates, rejected = parse_feed(data, source, window_days=window_days)
            outcome.update(candidateCount=len(candidates), rejectedEntries=rejected)
            for candidate in candidates:
                prior = existing.get(candidate["id"])
                if prior:
                    candidate["discoveredAt"] = prior["discoveredAt"]
                    candidate["bodyAttempts"] = prior.get("bodyAttempts", [])
                    candidate["metadataHistory"] = prior.get("metadataHistory", [])
                    if prior["metadataFingerprint"] != candidate["metadataFingerprint"]:
                        candidate["metadataHistory"].append({key: value for key, value in prior.items() if key not in {"metadataHistory", "bodyAttempts"}})
                use_cache(state, candidate)
                existing[candidate["id"]] = candidate
        except FetchFailure as error:
            outcome.update(error.outcome)
        except (ValueError, OSError, ET.ParseError) as error:
            outcome.update(status="failed", error=str(error), errorType=type(error).__name__)
        outcome["completedAt"] = iso_now()
        manifest["candidates"] = list(existing.values())
        phase["checkpoint"]()
    phase["sourceAttempts"] = len(config["sources"])
    phase["candidateCount"] = len(manifest["candidates"])


def hydrate(config, state, manifest, phase, fetcher, ids, refresh=False):
    candidates = {candidate["id"]: candidate for candidate in manifest["candidates"]}
    sources = {source["id"]: source for source in config["sources"]}
    if not ids or len(ids) > 12 or len(set(ids)) != len(ids):
        raise ValueError("hydrate requires 1–12 unique explicitly selected candidate IDs")
    if any(not CANDIDATE_ID.fullmatch(identifier) or identifier not in candidates for identifier in ids):
        raise ValueError("hydrate contains an invalid or undiscovered candidate ID")
    phase["selectedIds"] = ids
    phase["refreshRequested"] = refresh
    for identifier in ids:
        candidate = candidates[identifier]
        outcome = {"phaseId": phase["id"], "attemptedAt": iso_now(), "status": "running", "cacheBypassed": refresh}
        candidate.setdefault("bodyAttempts", []).append(outcome)
        phase["checkpoint"]()
        if not refresh and use_cache(state, candidate):
            outcome.update(status="cache-reused", notice=CACHE_NOTICE, contentHash=candidate["contentHash"], bodyPath=candidate["bodyPath"])
        else:
            try:
                data, response = fetcher.fetch(candidate["url"], sources[candidate["sourceId"]])
                outcome.update(response)
                raw_path = f"runs/{manifest['runId']}/raw/{phase['id']}/{identifier}.html"
                atomic_bytes(state / raw_path, data)
                outcome["rawPath"] = raw_path
                text, scope, evidence = extract_body(data, response["contentType"], response["finalUrl"])
                encoded = text.encode("utf-8")
                digest = hashlib.sha256(encoded).hexdigest()
                body_path = f"materials/{identifier}/versions/{digest}/body.txt"
                atomic_bytes(state / body_path, encoded)
                atomic_bytes(state / "materials" / identifier / "body.txt", encoded)
                candidate.update(bodyStatus="readable", bodyPath=body_path, contentHash=digest,
                                 materialScope=scope, bodyChars=len(text), extractionEvidence=evidence,
                                 bodyFetchedAt=iso_now(), bodyCacheReuse=None)
                atomic_json(state / "materials" / identifier / "metadata.json", {
                    key: candidate[key] for key in ("id", "url", "metadataFingerprint", "bodyPath", "contentHash", "materialScope", "bodyChars", "extractionEvidence", "bodyFetchedAt")
                })
                outcome.update(contentHash=digest, bodyPath=body_path, materialScope=scope, bodyChars=len(text), extractionEvidence=evidence)
            except FetchFailure as error:
                outcome.update(error.outcome)
                candidate.update(bodyStatus="failed", bodyCacheReuse=None)
            except (ValueError, OSError) as error:
                outcome.update(status="failed", error=str(error), errorType=type(error).__name__)
                candidate.update(bodyStatus="failed", bodyCacheReuse=None)
        outcome["completedAt"] = iso_now()
        phase["checkpoint"]()


def run_operation(command, config, state_dir, run_id, window_days=14, ids=None, opener=None, refresh=False):
    if command not in {"collect", "hydrate"}:
        raise ValueError("unknown operation")
    if type(window_days) is not int or not 1 <= window_days <= 90:
        raise ValueError("window-days must be between 1 and 90")
    if not RUN_ID.fullmatch(run_id):
        raise ValueError("invalid run-id")
    state = validate_state_dir(state_dir)
    with writer_lock(state):
        manifest, manifest_path = load_manifest(state, run_id, config)
        if command == "hydrate" and not manifest_path.exists():
            raise ValueError("collect this run before hydrating candidates")
        start = time.monotonic()
        previous_elapsed = manifest["usage"]["elapsedMs"]
        phase = {"id": f"{command}-{len(manifest['phases']) + 1:04d}", "kind": command,
                 "startedAt": iso_now(), "status": "running"}
        manifest["phases"].append(phase)

        def checkpoint():
            manifest["updatedAt"] = iso_now()
            manifest["usage"]["elapsedMs"] = previous_elapsed + round((time.monotonic() - start) * 1000)
            saved = {**manifest, "phases": [{key: value for key, value in item.items() if key != "checkpoint"} for item in manifest["phases"]]}
            atomic_json(manifest_path, saved)

        phase["checkpoint"] = checkpoint
        checkpoint()
        fetcher = Fetcher(config["limits"], manifest["usage"], opener=opener, checkpoint=checkpoint)
        try:
            if command == "collect":
                collect(config, state, manifest, phase, fetcher, window_days)
            else:
                hydrate(config, state, manifest, phase, fetcher, ids or [], refresh=refresh)
            phase["status"] = "completed"
        except Exception as error:
            phase.update(status="failed", error=str(error), errorType=type(error).__name__)
            raise
        finally:
            phase["completedAt"] = iso_now()
            checkpoint()
            del phase["checkpoint"]
        return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("collect", "hydrate"):
        subparser = subparsers.add_parser(name)
        subparser.add_argument("--sources", required=True, type=Path)
        subparser.add_argument("--state-dir", required=True, type=Path)
        subparser.add_argument("--run-id", required=True)
        if name == "collect":
            subparser.add_argument("--window-days", type=int, default=14)
        else:
            subparser.add_argument("--ids", required=True, help="comma-separated candidate IDs, at most 12")
            subparser.add_argument("--refresh", action="store_true", help="bypass body cache; preserve earlier attempts and immutable body versions")
    args = parser.parse_args(argv)
    try:
        config = read_config(args.sources)
        manifest = run_operation(args.command, config, args.state_dir, args.run_id,
                                 window_days=getattr(args, "window_days", 14),
                                 ids=args.ids.split(",") if args.command == "hydrate" else None,
                                 refresh=getattr(args, "refresh", False))
        print(json.dumps({"runId": manifest["runId"], "manifestPath": str(args.state_dir.expanduser().resolve() / "runs" / args.run_id / "manifest.json"), "candidateCount": len(manifest["candidates"]), "usage": manifest["usage"]}, ensure_ascii=False))
        return 0
    except (ValueError, OSError, ET.ParseError) as error:
        print(f"collector: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
