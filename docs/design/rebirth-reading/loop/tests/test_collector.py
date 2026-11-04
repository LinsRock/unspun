"""Offline contracts for bounded discovery, material retrieval, and evidence replay."""

from contextlib import contextmanager
from datetime import datetime, timezone
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

MODULE_PATH = Path(__file__).resolve().parents[1] / "collector.py"
SPEC = importlib.util.spec_from_file_location("collector", MODULE_PATH)
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)

NOW = datetime(2026, 11, 4, 8, tzinfo=timezone.utc)
SOURCE = {"id": "sample", "name": "Sample", "url": "https://news.example/feed", "allowedHosts": ["news.example"], "domain": "technology", "maxItems": 8}
CONFIG = {"schemaVersion": 1, "sources": [SOURCE], "limits": {"maxRequests": 24, "maxBytes": 2_000_000, "timeoutSeconds": 10}}


def rss(items=None):
    if items is None:
        items = '<item><title>A useful item</title><link>https://news.example/article?utm_source=rss&amp;id=1#top</link><pubDate>Wed, 04 Nov 2026 01:00:00 +0800</pubDate><author>Editor</author></item>'
    return f"<rss version='2.0'><channel>{items}</channel></rss>".encode()


def article(text=None):
    return ("<html><nav>navigation junk</nav><article><h1>Useful title</h1><p>" + (text or "A factual discussion about the subject. " * 8) + "</p><script>secretScript()</script><footer>footer junk</footer></article></html>").encode()


class Response(io.BytesIO):
    def __init__(self, content, status=200, content_type="application/rss+xml", headers=None):
        super().__init__(content)
        self.status = status
        self.headers = {"Content-Type": content_type, **(headers or {})}


class Opener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request.full_url, timeout))
        if not self.responses:
            raise AssertionError("unexpected network request")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FeedTests(unittest.TestCase):
    def parse(self, data):
        return collector.parse_feed(data, SOURCE, NOW)

    def test_rss_retains_source_timezone_and_deduplicates_tracking_urls(self):
        original = '<item><title>Item</title><link>https://news.example/a?id=7&amp;utm_source=feed#top</link><pubDate>Wed, 04 Nov 2026 01:00:00 +0800</pubDate></item>'
        duplicate = '<item><title>Same</title><link>https://news.example/a?id=7</link></item>'
        candidates, rejected = self.parse(rss(original + duplicate))
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["publishedAt"], "2026-11-04T01:00:00+08:00")
        self.assertEqual(candidates[0]["disposition"], "recent")
        self.assertEqual(candidates[0]["url"], "https://news.example/a?id=7")
        self.assertEqual(rejected[0]["reason"], "duplicate canonical URL")

    def test_atom_updated_is_not_fabricated_publication_date(self):
        data = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Unknown original date</title><link href="/2026/11/04/article"/><updated>2026-11-04T08:00:00Z</updated><author><name>Author</name></author></entry><entry><title>Published item</title><link href="/two"/><published>2026-11-03T11:15:00+08:00</published></entry></feed>'''
        candidates, _ = self.parse(data)
        self.assertIsNone(candidates[0]["publishedAt"])
        self.assertEqual(candidates[0]["disposition"], "unknown-date")
        self.assertEqual(candidates[0]["author"], "Author")
        self.assertEqual(candidates[1]["publishedAt"], "2026-11-03T11:15:00+08:00")

    def test_dates_are_source_values_not_discovery_or_url_guesses(self):
        items = ''.join(f'<item><title>{index}</title><link>https://news.example/2026/11/04/{index}</link><pubDate>{date}</pubDate></item>' for index, date in enumerate(["nonsense", "2026-11-04", "2026-11-04T01:00:00", "Thu, 01 Jan 2015 10:00:00 +0000", "2028-01-01T00:00:00Z"]))
        candidates, _ = self.parse(rss(items))
        self.assertEqual([item["disposition"] for item in candidates], ["unknown-date"] * 3 + ["outside-window"] * 2)
        self.assertTrue(all(item["publishedAt"] is None for item in candidates[:3]))
        self.assertEqual(candidates[-1]["dateIssue"], "future-source-publication-date")

    def test_malformed_nonfeed_and_entity_documents_fail(self):
        for value in [b"<rss><channel>", b"<html>not a feed</html>", b'<!DOCTYPE rss [<!ENTITY x "expanded">]><rss><channel/></rss>']:
            with self.subTest(value=value), self.assertRaises((ValueError, collector.ET.ParseError)):
                self.parse(value)

    def test_canonicalization_preserves_meaningful_query_bytes(self):
        self.assertEqual(collector.normalize_url("https://NEWS.example:443/a?key=a%2Fb&x=1&x=2&UTM_medium=feed#x"), "https://news.example/a?key=a%2Fb&x=1&x=2")
        self.assertNotEqual(collector.normalize_url("https://news.example/a?id=1"), collector.normalize_url("https://news.example/a?id=2"))
        for url in ["file:///tmp/x", "http://127.0.0.1/", "http://localhost/x", "https://user:password@news.example/"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                collector.normalize_url(url)

    def test_off_allowlist_entries_are_rejected_not_hydrated(self):
        candidates, rejected = self.parse(rss('<item><title>Foreign</title><link>https://other.example/a</link></item>'))
        self.assertEqual(candidates, [])
        self.assertIn("allowlist", rejected[0]["reason"])


class ExtractionTests(unittest.TestCase):
    def test_explicit_body_excludes_navigation_script_and_footer(self):
        text, scope, evidence = collector.extract_body(article(), "text/html; charset=UTF-8")
        self.assertEqual(scope, "body")
        self.assertEqual(evidence, "article")
        for excluded in ["navigation junk", "secretScript", "footer junk"]:
            self.assertNotIn(excluded, text)

    def test_wrapper_body_and_ambiguous_excerpt_have_distinct_scope(self):
        text = "Readable source text with sufficient detail. " * 70
        body, scope, _ = collector.extract_body(f'<div class="entry-content"><p>{text}</p></div>'.encode(), "text/html")
        self.assertEqual(scope, "body")
        self.assertGreater(len(body), 2000)
        excerpt, scope, _ = collector.extract_body(f'<html><div>{text}</div></html>'.encode(), "text/html")
        self.assertEqual(scope, "excerpt")
        self.assertEqual(len(excerpt), 2000)

    def test_short_challenge_and_non_html_are_failures(self):
        for value, mime in [(b"<html>Login required</html>", "text/html"), (b"some binary material", "application/octet-stream")]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                collector.extract_body(value, mime)

    def test_observed_publisher_wrappers_require_correct_host_and_container(self):
        text = "A publisher's actual article paragraph with sufficient detail. " * 6
        cases = [
            ("https://www.qbitai.com/2026/11/123.html", '<div class="content"><div class="article">' + text + '</div><div class="xiangguan">Related stories must stay out</div></div>', "www.qbitai.com div.content > div.article"),
            ("https://www.solidot.org/story?sid=1", '<div class="articleBox"><div class="articles"><div class="p_mainnew"><p>' + text + '</p></div></div></div><div id="footer">Footer must stay out</div>', "www.solidot.org .articleBox .p_mainnew"),
        ]
        for url, markup, expected_evidence in cases:
            with self.subTest(url=url):
                body, scope, evidence = collector.extract_body(markup.encode(), "text/html", url)
                self.assertEqual(scope, "body")
                self.assertEqual(evidence, expected_evidence)
                self.assertNotIn("must stay out", body)
                _, unknown_scope, _ = collector.extract_body(markup.encode(), "text/html", "https://news.example/a")
                self.assertEqual(unknown_scope, "excerpt")
        _, scope, _ = collector.extract_body(('<div class="article">' + text + '</div>').encode(), "text/html", "https://www.qbitai.com/a")
        self.assertEqual(scope, "excerpt")


class RunTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="unspun-collector-test-")
        self.state = Path(self.directory.name)
        self.clock = patch.object(collector, "utc_now", return_value=NOW)
        self.clock.start()

    def tearDown(self):
        self.clock.stop()
        self.directory.cleanup()

    def run_collect(self, opener, run_id="sample", config=CONFIG):
        return collector.run_operation("collect", config, self.state, run_id, opener=opener)

    def test_collect_never_downloads_or_selects_discovered_bodies(self):
        opener = Opener([Response(rss())])
        manifest = self.run_collect(opener)
        self.assertEqual(len(opener.requests), 1)
        self.assertEqual(manifest["candidates"][0]["bodyStatus"], "pending")
        self.assertIsNone(manifest["candidates"][0]["bodyPath"])
        self.assertNotIn("publication", manifest)
        self.assertNotIn("selected", manifest["candidates"][0])
        self.assertEqual(manifest["usage"]["modelCalls"], 0)
        self.assertIsNone(manifest["usage"]["modelCost"])

    def test_failures_are_appended_and_prior_run_is_preserved(self):
        first = self.run_collect(Opener([Response(b"broken xml")]))
        self.assertEqual(first["sources"][0]["status"], "failed")
        second = self.run_collect(Opener([Response(rss())]))
        self.assertEqual([outcome["status"] for outcome in second["sources"]], ["failed", "ok"])
        snapshot = (self.state / "runs/sample/manifest.json").read_bytes()
        self.run_collect(Opener([urllib.error.URLError("offline")]), run_id="another")
        self.assertEqual((self.state / "runs/sample/manifest.json").read_bytes(), snapshot)
        other = json.loads((self.state / "runs/another/manifest.json").read_text())
        self.assertEqual(other["sources"][0]["errorType"], "URLError")

    def test_http_failures_do_not_disappear_from_source_outcomes(self):
        error = urllib.error.HTTPError(SOURCE["url"], 403, "Forbidden", {}, io.BytesIO())
        manifest = self.run_collect(Opener([error]))
        self.assertEqual(manifest["sources"][0]["httpStatus"], 403)
        self.assertEqual(manifest["sources"][0]["status"], "failed")
        self.assertEqual(manifest["usage"]["requestCount"], 1)

    def test_explicit_hydration_cache_replay_and_immutable_prior_material(self):
        first = self.run_collect(Opener([Response(rss())]))
        identifier = first["candidates"][0]["id"]
        hydrated = collector.run_operation("hydrate", CONFIG, self.state, "sample", ids=[identifier], opener=Opener([Response(article(), content_type="text/html")]))
        material = hydrated["candidates"][0]
        old_path = material["bodyPath"]
        old_bytes = (self.state / old_path).read_bytes()
        replay = collector.run_operation("hydrate", CONFIG, self.state, "sample", ids=[identifier], opener=Opener([]))
        self.assertEqual(replay["usage"]["requestCount"], 2)
        self.assertEqual(replay["candidates"][0]["bodyAttempts"][-1]["status"], "cache-reused")
        self.assertIn("freshness was not rechecked", replay["candidates"][0]["bodyCacheReuse"]["notice"])
        another = self.run_collect(Opener([Response(rss())]), run_id="another")
        self.assertEqual(another["candidates"][0]["bodyPath"], old_path)
        changed = rss().replace(b"A useful item", b"A revised item")
        newer = self.run_collect(Opener([Response(changed)]), run_id="newer")
        self.assertEqual(newer["candidates"][0]["bodyStatus"], "pending")
        collector.run_operation("hydrate", CONFIG, self.state, "newer", ids=[identifier], opener=Opener([Response(article("Updated substantive material. " * 20), content_type="text/html")]))
        self.assertEqual((self.state / old_path).read_bytes(), old_bytes)

    def test_bad_cache_hash_forces_new_fetch(self):
        first = self.run_collect(Opener([Response(rss())]))
        identifier = first["candidates"][0]["id"]
        result = collector.run_operation("hydrate", CONFIG, self.state, "sample", ids=[identifier], opener=Opener([Response(article(), content_type="text/html")]))
        (self.state / result["candidates"][0]["bodyPath"]).write_text("corrupted")
        opener = Opener([Response(article(), content_type="text/html")])
        collector.run_operation("hydrate", CONFIG, self.state, "sample", ids=[identifier], opener=opener)
        self.assertEqual(len(opener.requests), 1)

    def test_refresh_bypasses_unchanged_cache_and_preserves_original_evidence(self):
        first = self.run_collect(Opener([Response(rss())]))
        identifier = first["candidates"][0]["id"]
        original = collector.run_operation("hydrate", CONFIG, self.state, "sample", ids=[identifier], opener=Opener([Response(article(), content_type="text/html")]))
        original_material = original["candidates"][0]
        original_path = original_material["bodyPath"]
        original_bytes = (self.state / original_path).read_bytes()
        original_attempt = original_material["bodyAttempts"][0]
        original_raw = (self.state / original_attempt["rawPath"]).read_bytes()
        opener = Opener([Response(article("Refreshed article detail with a distinct content hash. " * 10), content_type="text/html")])
        refreshed = collector.run_operation("hydrate", CONFIG, self.state, "sample", ids=[identifier], opener=opener, refresh=True)
        candidate = refreshed["candidates"][0]
        self.assertEqual(len(opener.requests), 1)
        self.assertEqual(refreshed["usage"]["requestCount"], 3)
        self.assertTrue(refreshed["phases"][-1]["refreshRequested"])
        self.assertTrue(candidate["bodyAttempts"][-1]["cacheBypassed"])
        self.assertIsNone(candidate["bodyCacheReuse"])
        self.assertEqual(candidate["bodyAttempts"][0], original_attempt)
        self.assertEqual((self.state / original_path).read_bytes(), original_bytes)
        self.assertEqual((self.state / original_attempt["rawPath"]).read_bytes(), original_raw)
        self.assertNotEqual(candidate["bodyPath"], original_path)
        self.assertNotEqual(candidate["bodyAttempts"][-1]["rawPath"], original_attempt["rawPath"])
        failed = collector.run_operation("hydrate", CONFIG, self.state, "sample", ids=[identifier], opener=Opener([urllib.error.URLError("refresh unavailable")]), refresh=True)
        self.assertEqual(failed["candidates"][0]["bodyStatus"], "failed")
        self.assertEqual(failed["candidates"][0]["bodyAttempts"][0], original_attempt)
        self.assertEqual((self.state / original_path).read_bytes(), original_bytes)

    def test_failed_hydration_and_replay_preserve_original_failure(self):
        first = self.run_collect(Opener([Response(rss())]))
        identifier = first["candidates"][0]["id"]
        fail = collector.run_operation("hydrate", CONFIG, self.state, "sample", ids=[identifier], opener=Opener([Response(b"<html>Login required</html>", content_type="text/html")]))
        self.assertEqual(fail["candidates"][0]["bodyStatus"], "failed")
        success = collector.run_operation("hydrate", CONFIG, self.state, "sample", ids=[identifier], opener=Opener([Response(article(), content_type="text/html")]))
        self.assertEqual([item["status"] for item in success["candidates"][0]["bodyAttempts"]], ["failed", "ok"])

    def test_unknown_selection_is_rejected_before_network(self):
        self.run_collect(Opener([Response(rss())]))
        for ids in [["live-" + "a" * 24], ["$(touch /tmp/should-not-exist)"], ["x"] * 13]:
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                collector.run_operation("hydrate", CONFIG, self.state, "sample", ids=ids, opener=Opener([]))

    def test_redirect_allowlist_request_and_byte_bounds(self):
        foreign = Response(b"", status=302, headers={"Location": "https://other.example/a"})
        manifest = self.run_collect(Opener([foreign]))
        self.assertIn("allowlist", manifest["sources"][0]["error"])
        limited = {**CONFIG, "limits": {**CONFIG["limits"], "maxRequests": 1}}
        self.run_collect(Opener([Response(rss())]), run_id="limited", config=limited)
        replay = self.run_collect(Opener([]), run_id="limited", config=limited)
        self.assertEqual(replay["usage"]["requestCount"], 1)
        self.assertIn("request limit", replay["sources"][-1]["error"])
        small = {**CONFIG, "limits": {**CONFIG["limits"], "maxBytes": 10}}
        overflow = self.run_collect(Opener([Response(rss())]), run_id="small", config=small)
        self.assertIn("byte limit", overflow["sources"][0]["error"])

    def test_configuration_drift_and_unsafe_paths_are_rejected(self):
        self.run_collect(Opener([Response(rss())]))
        with self.assertRaisesRegex(ValueError, "configuration changed"):
            self.run_collect(Opener([]), config={**CONFIG, "limits": {**CONFIG["limits"], "maxRequests": 23}})
        with self.assertRaises(ValueError):
            self.run_collect(Opener([]), run_id="../escape")
        with self.assertRaisesRegex(ValueError, "outside the repository"):
            collector.validate_state_dir(MODULE_PATH.parent / "state")

    def test_one_writer_lock_and_atomic_failure_keep_previous_json(self):
        with collector.writer_lock(self.state):
            with self.assertRaisesRegex(ValueError, "another collector"):
                with collector.writer_lock(self.state):
                    self.fail("second writer entered")
        with collector.writer_lock(self.state):
            pass
        path = self.state / "record.json"
        collector.atomic_json(path, {"original": True})
        before = path.read_bytes()
        with patch.object(collector.os, "replace", side_effect=OSError("simulated failure")):
            with self.assertRaises(OSError):
                collector.atomic_json(path, {"original": False})
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(self.state.glob(".record.json.*")), [])


if __name__ == "__main__":
    unittest.main()
