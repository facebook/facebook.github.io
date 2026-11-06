#!/usr/bin/env python3
"""Refresh known HTML routes from configured public sitemaps, explicitly."""
from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, unquote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from scripts import build

LIMIT = 10 * 1024 * 1024
MAX_SITEMAPS = 50
MAX_ROUTES = 20000


def relative_route(url: str, project: dict) -> str | None:
    """Accept only this canonical site or its two known organization aliases."""
    parsed, base = urlsplit(url), urlsplit(project["target_base"])
    if parsed.scheme not in ("http", "https") or parsed.username or parsed.password or parsed.query or parsed.fragment:
        return None
    if parsed.netloc.lower() == base.netloc.lower() and parsed.path.startswith(base.path):
        return parsed.path[len(base.path):]
    legacy_prefix = "/" + project["prefix"] + "/"
    if parsed.hostname in ("facebook.github.io", "meta.github.io") and parsed.path.startswith(legacy_prefix):
        return parsed.path[len(legacy_prefix):]
    return None


def sitemap_url(url: str, project: dict) -> str:
    route = relative_route(url, project)
    if route is None or any(part in (".", "..") for part in unquote(route).split("/")):
        raise ValueError(f"sitemap outside project scope: {url}")
    return project["target_base"] + route


class ScopedRedirects(HTTPRedirectHandler):
    def __init__(self, project):
        self.project = project
        super().__init__()

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return super().redirect_request(req, fp, code, msg, headers, sitemap_url(newurl, self.project))


def fetch(url: str, project: dict) -> bytes:
    opener = build_opener(ScopedRedirects(project))
    request = Request(sitemap_url(url, project), headers={"User-Agent": "facebook-pages-redirects/1.0"})
    with opener.open(request, timeout=20) as response:
        data = response.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise ValueError(f"sitemap too large: {url}")
    if data.startswith(b"\x1f\x8b"):
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as compressed:
            data = compressed.read(LIMIT + 1)
        if len(data) > LIMIT:
            raise ValueError(f"expanded sitemap too large: {url}")
    return data


def collect(project: dict, fetcher=fetch) -> tuple[list[str], dict[str, int]]:
    pending = list(project.get("sitemaps", []))
    visited = set()
    routes = set(project["routes"]) | {""}
    ignored = 0
    excluded = set(project.get("excluded_routes", []))
    while pending:
        source = sitemap_url(pending.pop(0), project)
        if source in visited:
            continue
        if len(visited) >= MAX_SITEMAPS:
            raise ValueError(f"too many sitemaps for {project['prefix']}")
        visited.add(source)
        root = ET.fromstring(fetcher(source, project))
        kind = root.tag.rsplit("}", 1)[-1]
        if kind not in ("urlset", "sitemapindex"):
            raise ValueError(f"not a sitemap: {source}")
        for element in root:
            location = next((item.text for item in element if item.tag.rsplit("}", 1)[-1] == "loc"), None)
            if not location:
                continue
            if kind == "sitemapindex":
                pending.append(sitemap_url(location.strip(), project))
                continue
            route = relative_route(location.strip(), project)
            if route is None:
                ignored += 1
                continue
            try:
                path = build.route_path(route)
            except ValueError:
                ignored += 1
                continue
            # Keep URI spelling so the builder decodes exactly once, including
            # literal percent escapes such as a%2520b. Normalize index aliases.
            if path == "index.html":
                route = ""
            elif path.endswith("/index.html"):
                route = quote(path[:-len("index.html")], safe="/!$&'()*+,-.:;=@_~")
            if route in excluded:
                ignored += 1
                continue
            routes.add(route)
            if len(routes) > MAX_ROUTES:
                raise ValueError(f"too many routes for {project['prefix']}")
    return sorted(routes), {"sitemaps": len(visited), "routes": len(routes), "ignored": ignored}


def refresh(config: dict, fetcher=fetch) -> tuple[dict, list[dict]]:
    # Preserve explicitly recorded old routes; failed refreshes never erase them.
    updated = json.loads(json.dumps(config))
    reports = []
    for project in updated["projects"]:
        if not project.get("sitemaps"):
            continue
        project["routes"], report = collect(project, fetcher)
        reports.append({"prefix": project["prefix"], **report})
    return updated, reports


def atomic_write(path: Path, text: str) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=build.ROOT / "sites.json")
    parser.add_argument("--write", action="store_true", help="replace config only after all fetches and build validation succeed")
    args = parser.parse_args()
    # Validate original configuration before any network request.
    build.load_config(args.config)
    updated, reports = refresh(json.loads(args.config.read_text(encoding="utf-8")))
    text = json.dumps(updated, ensure_ascii=False, indent=2) + "\n"
    with tempfile.TemporaryDirectory() as temp:
        draft = Path(temp) / "sites.json"
        draft.write_text(text, encoding="utf-8")
        build.build(draft, Path(temp) / "site")
    if args.write:
        atomic_write(args.config, text)
        print(json.dumps(reports, indent=2))
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
