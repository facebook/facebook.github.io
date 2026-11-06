import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import refresh

PROJECT = {
    "prefix": "watchman", "target_base": "https://meta.github.io/watchman/",
    "routes": ["", "manually-recorded-old-page"],
    "sitemaps": ["https://meta.github.io/watchman/sitemap.xml"],
}


def xml(kind, locations):
    child = "sitemap" if kind == "sitemapindex" else "url"
    return (f'<{kind} xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' +
            "".join(f"<{child}><loc>{location}</loc></{child}>" for location in locations) +
            f"</{kind}>").encode()


class RefreshTest(unittest.TestCase):
    def test_collects_canonical_and_legacy_urls_preserving_manual_routes(self):
        locations = [
            "https://meta.github.io/watchman/docs/cmd/query",
            "http://facebook.github.io/watchman/docs/install/",
            "https://meta.github.io/watchman/index.html",
            "https://meta.github.io/watchman/docs/reference/index.html",
            "https://example.org/other-project/",
            "https://meta.github.io/watchman/asset.pdf",
        ]
        routes, report = refresh.collect(PROJECT, lambda *_: xml("urlset", locations))
        self.assertEqual(routes, ["", "docs/cmd/query", "docs/install/", "docs/reference/", "manually-recorded-old-page"])
        self.assertEqual(report, {"sitemaps": 1, "routes": 5, "ignored": 2})

    def test_explicitly_excluded_stale_routes_are_not_reintroduced(self):
        project = {**PROJECT, "excluded_routes": ["stale"]}
        routes, report = refresh.collect(project, lambda *_: xml("urlset", ["https://meta.github.io/watchman/stale"]))
        self.assertNotIn("stale", routes)
        self.assertEqual(report["ignored"], 1)

    def test_percent_encoded_route_is_not_decoded_twice(self):
        route = "https://meta.github.io/watchman/a%2520b"
        routes, _ = refresh.collect(PROJECT, lambda *_: xml("urlset", [route]))
        self.assertIn("a%2520b", routes)
        self.assertEqual(refresh.build.route_path("a%2520b"), "a%20b")

    def test_custom_domain_strips_only_its_base_path_or_legacy_prefix(self):
        project = {**PROJECT, "target_base": "https://docs.example.org/documentation/"}
        self.assertEqual(refresh.relative_route("https://docs.example.org/documentation/guide", project), "guide")
        self.assertEqual(refresh.relative_route("https://facebook.github.io/watchman/guide", project), "guide")
        self.assertIsNone(refresh.relative_route("https://docs.example.org/other/guide", project))
        self.assertIsNone(refresh.relative_route("https://meta.github.io/other-project/guide", project))

    def test_recurses_and_deduplicates_sitemap_indexes(self):
        source = "https://meta.github.io/watchman/sitemap.xml"
        part = "https://meta.github.io/watchman/part.xml"
        documents = {
            source: xml("sitemapindex", [part, source, part]),
            part: xml("urlset", ["https://meta.github.io/watchman/docs/cmd/query"]),
        }
        calls = []
        def fetch(url, project):
            calls.append(url)
            return documents[url]
        routes, report = refresh.collect(PROJECT, fetch)
        self.assertIn("docs/cmd/query", routes)
        self.assertEqual(calls, [source, part])
        self.assertEqual(report["sitemaps"], 2)

    def test_rejects_cross_origin_sitemap_indexes_and_traversal(self):
        for location in ["https://evil.example/sitemap.xml", "https://meta.github.io/other/part.xml", "https://meta.github.io/watchman/%2e%2e/other.xml"]:
            with self.subTest(location=location), self.assertRaises(ValueError):
                refresh.collect(PROJECT, lambda *_: xml("sitemapindex", [location]))

    def test_refresh_failure_does_not_modify_input(self):
        original = {"version": 1, "projects": [PROJECT]}
        before = json.dumps(original, sort_keys=True)
        def failed(*_):
            raise OSError("offline")
        with self.assertRaises(OSError):
            refresh.refresh(original, failed)
        self.assertEqual(json.dumps(original, sort_keys=True), before)

    def test_sitemap_count_bound(self):
        with patch.object(refresh, "MAX_SITEMAPS", 1), self.assertRaisesRegex(ValueError, "too many sitemaps"):
            refresh.collect(PROJECT, lambda *_: xml("sitemapindex", ["https://meta.github.io/watchman/part.xml"]))

    def test_route_count_bound(self):
        with patch.object(refresh, "MAX_ROUTES", 2), self.assertRaisesRegex(ValueError, "too many routes"):
            refresh.collect(PROJECT, lambda *_: xml("urlset", ["https://meta.github.io/watchman/new"]))

    def test_invalid_xml_and_non_sitemap_documents_fail(self):
        for document in [b"not xml", b"<html></html>"]:
            with self.subTest(document=document), self.assertRaises((ValueError, refresh.ET.ParseError)):
                refresh.collect(PROJECT, lambda *_: document)

    def test_atomic_write_preserves_original_on_interruption_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "sites.json"
            path.write_text("original")
            for method in ("fsync", "replace"):
                with self.subTest(method=method), patch.object(refresh.os, method, side_effect=OSError("interrupted")):
                    with self.assertRaises(OSError):
                        refresh.atomic_write(path, "replacement")
                self.assertEqual(path.read_text(), "original")
                self.assertEqual([p.name for p in Path(temp).iterdir()], ["sites.json"])
            refresh.atomic_write(path, "replacement")
            self.assertEqual(path.read_text(), "replacement")

    def test_rejects_urls_with_credentials_query_or_fragment(self):
        for url in ["https://user:pw@meta.github.io/watchman/guide", "https://meta.github.io/watchman/guide?next=a", "https://meta.github.io/watchman/guide#a", "file:///watchman/guide"]:
            with self.subTest(url=url):
                self.assertIsNone(refresh.relative_route(url, PROJECT))


if __name__ == "__main__":
    unittest.main()
