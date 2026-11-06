from __future__ import annotations

import functools
import json
import tempfile
import threading
import unittest
from html.parser import HTMLParser
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from scripts import build
from scripts.serve import PagesHandler


class Tags(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.tags = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / "sites.json"
        self.output = self.root / "output"
        self.projects = [{
            "prefix": "watchman", "target_base": "https://meta.github.io/watchman/",
            "routes": ["", "docs/cmd/query", "docs/install/", "old.html", "a%20b/", "caf%C3%A9"],
        }, {
            "prefix": "PathPicker", "target_base": "https://example.org/docs/",
            "routes": ["", "guide"],
        }]
        self.save()

    def save(self):
        self.config.write_text(json.dumps({"version": 1, "projects": self.projects}))

    def run_build(self):
        self.save()
        return build.build(self.config, self.output)

    def test_build_generates_canonical_meta_refresh_and_aliases(self):
        stats = self.run_build()
        self.assertEqual(stats["projects"], 2)
        expected = {
            "watchman/index.html": "https://meta.github.io/watchman/",
            "watchman/docs/cmd/query.html": "https://meta.github.io/watchman/docs/cmd/query",
            "watchman/docs/cmd/query/index.html": "https://meta.github.io/watchman/docs/cmd/query",
            "watchman/docs/install.html": "https://meta.github.io/watchman/docs/install/",
            "watchman/docs/install/index.html": "https://meta.github.io/watchman/docs/install/",
            "watchman/old.html": "https://meta.github.io/watchman/old.html",
            "watchman/a b/index.html": "https://meta.github.io/watchman/a%20b/",
            "watchman/café.html": "https://meta.github.io/watchman/caf%C3%A9",
            "PathPicker/guide.html": "https://example.org/docs/guide",
        }
        for file, target in expected.items():
            with self.subTest(file=file):
                tags = Tags((self.output / file).read_text()).tags
                self.assertIn(("meta", {"http-equiv": "refresh", "content": "0; url=" + target}), tags)
                self.assertIn(("link", {"rel": "canonical", "href": target}), tags)
                self.assertIn(("body", {"data-redirect-target": target}), tags)
        self.assertTrue((self.output / ".nojekyll").is_file())
        self.assertFalse((self.output / "CNAME").exists())
        self.assertNotIn('http-equiv="refresh"', (self.output / "404.html").read_text())
        self.assertIn('"pathpicker": {"preserve_path": true, "target_base": "https://example.org/docs/"}', (self.output / "404.html").read_text())

    def test_html_escaping(self):
        self.projects[0]["target_base"] = "https://example.org/a&b/"
        self.run_build()
        text = (self.output / "watchman/index.html").read_text()
        self.assertIn("https://example.org/a&amp;b/", text)
        self.assertIn(("link", {"rel": "canonical", "href": "https://example.org/a&b/"}), Tags(text).tags)

    def test_retired_project_redirects_all_routes_to_its_root(self):
        self.projects[0]["preserve_path"] = False
        self.run_build()
        target = self.projects[0]["target_base"]
        tags = Tags((self.output / "watchman/docs/cmd/query.html").read_text()).tags
        self.assertIn(("link", {"rel": "canonical", "href": target}), tags)
        self.assertIn('"preserve_path": false', (self.output / "404.html").read_text())
        self.projects[0]["preserve_path"] = "false"
        with self.assertRaisesRegex(ValueError, "boolean"):
            self.run_build()

    def test_root_is_a_directory_not_a_redirect_to_a_missing_meta_root(self):
        self.run_build()
        text = (self.output / "index.html").read_text()
        self.assertIn("Meta open source documentation", text)
        self.assertNotIn('http-equiv="refresh"', text)
        self.assertIn("https://example.org/docs/", text)

    def test_rebuild_is_deterministic_and_removes_stale_files(self):
        self.run_build()
        before = {p.relative_to(self.output): p.read_bytes() for p in self.output.rglob("*") if p.is_file()}
        self.run_build()
        after = {p.relative_to(self.output): p.read_bytes() for p in self.output.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.projects[0]["routes"] = [""]
        self.run_build()
        self.assertFalse((self.output / "watchman/docs").exists())

    def test_does_not_delete_arbitrary_directory(self):
        self.output.mkdir()
        sentinel = self.output / "important"
        sentinel.write_text("keep")
        with self.assertRaisesRegex(ValueError, "non-build"):
            self.run_build()
        self.assertEqual(sentinel.read_text(), "keep")

    def test_rejects_source_output_and_symlinks(self):
        with self.assertRaisesRegex(ValueError, "source"):
            build.build(self.config, build.ROOT)
        self.output.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.run_build()

    def test_rejects_conflicting_routes_before_replacing_output(self):
        self.run_build()
        original = (self.output / "watchman/index.html").read_bytes()
        self.projects[0]["routes"] = ["docs/query", "docs/query.html"]
        with self.assertRaisesRegex(ValueError, "conflicting"):
            self.run_build()
        self.assertEqual((self.output / "watchman/index.html").read_bytes(), original)

    def test_rejects_file_directory_and_support_collisions_before_deleting_output(self):
        self.run_build()
        original = (self.output / "watchman/index.html").read_bytes()
        for prefix in ["404.html", "redirect.js", "style.css", "index.html", "robots.txt", "build-report.json"]:
            with self.subTest(prefix=prefix):
                self.projects[0]["prefix"] = prefix
                with self.assertRaisesRegex(ValueError, "collision"):
                    self.run_build()
                self.assertEqual((self.output / "watchman/index.html").read_bytes(), original)
        self.projects[0]["prefix"] = "watchman"
        self.projects[0]["routes"] = ["a.html", "a.html/child"]
        with self.assertRaisesRegex(ValueError, "collision"):
            self.run_build()
        self.assertEqual((self.output / "watchman/index.html").read_bytes(), original)

    def test_invalid_routes(self):
        for route in ["../secret", "a/../../b", "/absolute", "a//b", "a/./b", "a\\b", "%2e%2e/a", "a%2fb", "a%5Cb", "a?x=1", "a#b", "a%00b", "file.pdf", "sitemap.xml", 7]:
            with self.subTest(route=route), self.assertRaises(ValueError):
                build.route_path(route)

    def test_invalid_targets(self):
        for target in ["http://example.org/", "//example.org/", "javascript:alert(1)", "https://facebook.github.io/", "https://user:pw@example.org/", "https://example.org/docs", "https://example.org/?next=x", "https://example.org/#a", "https://example.org:8080/", "https://example.org/\n", "https://example.org/\"/", None]:
            with self.subTest(target=target), self.assertRaises(ValueError):
                build.target_base(target)

    def test_rejects_encoded_or_invalid_hosts_and_self_redirects(self):
        for target in ["https://%66acebook.github.io/watchman/", "https://exa%mple.org/", "https://facebook.github.io./", "https://Facebook.GitHub.IO:443/", "https://example..org/", "https://-example.org/", "https://127.0.0.1/"]:
            with self.subTest(target=target), self.assertRaises(ValueError):
                build.target_base(target)
        self.assertEqual(build.target_base("https://meta.github.io/watchman/"), "https://meta.github.io/watchman/")

    def test_invalid_config(self):
        self.projects.append({"prefix": "WATCHMAN", "target_base": "https://example.org/", "routes": [""]})
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.run_build()
        self.projects.pop()
        for prefix in ["../oops", "-oops", ".", "a/b", "<script>"]:
            with self.subTest(prefix=prefix):
                self.projects[0]["prefix"] = prefix
                with self.assertRaises(ValueError):
                    self.run_build()

    def test_local_pages_resolution_returns_200_for_known_paths_404_for_fallback(self):
        self.run_build()
        server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(PagesHandler, directory=str(self.output)))
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"
        for path in ["/watchman/", "/watchman/docs/cmd/query", "/watchman/docs/cmd/query/", "/watchman/docs/cmd/query.html", "/watchman/docs/install", "/watchman/docs/install/", "/watchman/a%20b/", "/watchman/caf%C3%A9", "/PathPicker/guide"]:
            with self.subTest(path=path), urlopen(base + path, timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertIn(b'http-equiv="refresh"', response.read())
        for path in ["/watchman/unknown", "/unknown/guide"]:
            with self.subTest(path=path), self.assertRaises(HTTPError) as error:
                urlopen(base + path, timeout=5)
            self.assertEqual(error.exception.code, 404)
            self.assertIn(b"redirect-projects", error.exception.read())


if __name__ == "__main__":
    unittest.main()
