#!/usr/bin/env python3
"""Build static, crawlable redirects without third-party dependencies."""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
MARKER = ".facebook-pages-build"
PREFIX = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")


def target_base(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("target_base must be a URL string")
    parsed = urlsplit(value)
    hostname = (parsed.hostname or "").rstrip(".").lower()
    labels = hostname.split(".")
    valid_hostname = (
        len(hostname) <= 253
        and len(labels) >= 2
        and all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels)
        and not labels[-1].isdigit()
    )
    if (
        parsed.scheme != "https"
        or not valid_hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or parsed.query
        or parsed.fragment
        or not parsed.path.endswith("/")
        or any(ord(c) < 33 or c in '<>\\"' for c in value)
        or hostname == "facebook.github.io"
    ):
        raise ValueError(f"unsafe target_base: {value!r}")
    return value


def route_path(value: str) -> str:
    """Decode a sitemap URL path into its filesystem spelling, safely."""
    if not isinstance(value, str) or value.startswith("/"):
        raise ValueError(f"route must be relative: {value!r}")
    if re.search(r"%(?:2f|5c)", value, re.I):
        raise ValueError(f"encoded path separators are not supported: {value!r}")
    path = unquote(value, errors="strict")
    if (
        any(ord(c) < 32 or c in "\\?#" for c in path)
        or path.startswith("/")
        or any(part in (".", "..", "") for part in path.rstrip("/").split("/"))
        and path != ""
    ):
        raise ValueError(f"unsafe route: {value!r}")
    # Pages chooses MIME types by extension: a redirect .pdf/.xml is not HTML.
    if path and not path.endswith("/") and Path(path).suffix not in ("", ".html", ".htm"):
        raise ValueError(f"not an HTML page route: {value!r}")
    return path


def destination(base: str, route: str) -> str:
    return base + quote(route, safe="/!$&'()*+,-.:;=@_~")


def output_files(prefix: str, route: str) -> list[str]:
    if not route:
        return [f"{prefix}/index.html"]
    if route.endswith("/"):
        stem = route.rstrip("/")
        return [f"{prefix}/{stem}/index.html", f"{prefix}/{stem}.html"]
    if Path(route).suffix in (".html", ".htm"):
        return [f"{prefix}/{route}"]
    return [f"{prefix}/{route}.html", f"{prefix}/{route}/index.html"]


def document(title: str, body: str, head: str = "", attributes: str = "") -> str:
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(title)}</title>\n{head}"
        '<link rel="stylesheet" href="/style.css">\n</head>\n'
        f"<body{attributes}>\n<main>\n{body}</main>\n"
        '<script src="/redirect.js"></script>\n</body>\n</html>\n'
    )


def redirect_page(target: str) -> str:
    escaped = html.escape(target, quote=True)
    return document(
        "Documentation moved",
        '<h1>This documentation has moved</h1>\n'
        f'<p>Continue to <a id="destination" href="{escaped}">{escaped}</a>.</p>\n',
        f'<meta http-equiv="refresh" content="0; url={escaped}">\n'
        f'<link rel="canonical" href="{escaped}">\n',
        f' data-redirect-target="{escaped}"',
    )


def fallback_page(projects: dict[str, dict]) -> str:
    # Escape HTML-significant characters even inside a non-executable script.
    payload = json.dumps(projects, ensure_ascii=True, sort_keys=True).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return document(
        "Find the new documentation",
        '<h1>This documentation may have moved</h1>\n'
        '<p id="message">Find the project\'s current documentation below.</p>\n'
        '<p><a id="destination" href="/">Browse migrated projects</a></p>\n'
        '<noscript><p>Automatic recovery of unlisted links requires JavaScript. '
        '<a href="/">Browse migrated projects</a> instead.</p></noscript>\n'
        f'<script id="redirect-projects" type="application/json">{payload}</script>\n',
    )


def load_config(path: Path) -> list[dict]:
    config = json.loads(path.read_text(encoding="utf-8"))
    if config.get("version") != 1 or not isinstance(config.get("projects"), list):
        raise ValueError("expected configuration version 1 and a projects array")
    result = []
    seen = set()
    for project in config["projects"]:
        prefix = project.get("prefix")
        if not isinstance(prefix, str) or not PREFIX.fullmatch(prefix):
            raise ValueError(f"invalid project prefix: {prefix!r}")
        if prefix.casefold() in seen:
            raise ValueError(f"duplicate project prefix: {prefix!r}")
        seen.add(prefix.casefold())
        base = target_base(project.get("target_base"))
        routes = project.get("routes")
        if not isinstance(routes, list) or not routes:
            raise ValueError(f"{prefix}: routes must be a nonempty array")
        normalized = sorted(set(route_path(route) for route in routes) | {""})
        preserve_path = project.get("preserve_path", True)
        if not isinstance(preserve_path, bool):
            raise ValueError(f"{prefix}: preserve_path must be a boolean")
        result.append({"prefix": prefix, "target_base": base, "routes": normalized, "preserve_path": preserve_path})
    if not result:
        raise ValueError("at least one project is required")
    return sorted(result, key=lambda project: project["prefix"].casefold())


def build(config: Path, output: Path) -> dict[str, int]:
    projects = load_config(config)
    files: dict[str, tuple[str, str]] = {}
    mappings = {}
    route_count = 0
    for project in projects:
        prefix, base = project["prefix"], project["target_base"]
        mappings[prefix.casefold()] = {"target_base": base, "preserve_path": project["preserve_path"]}
        for route in project["routes"]:
            target = destination(base, route) if project["preserve_path"] else base
            route_count += 1
            for name in output_files(prefix, route):
                if name in files and files[name][0] != target:
                    raise ValueError(f"conflicting routes for {name}: {files[name][0]} vs {target}")
                files[name] = (target, redirect_page(target))

    # Check file-versus-directory collisions with all support files before
    # deleting any previous build (e.g. a project named redirect.js).
    support = {MARKER, "index.html", "404.html", "redirect.js", "style.css", ".nojekyll", "robots.txt", "build-report.json"}
    names = set(files) | support
    if set(files) & support:
        raise ValueError("redirect path conflicts with a support file")
    for name in names:
        for parent in Path(name).parents:
            if str(parent) in names:
                raise ValueError(f"file/directory output collision: {parent} and {name}")

    # Refuse accidental deletion of an arbitrary directory or source checkout.
    if output.is_symlink():
        raise ValueError("output cannot be a symlink")
    resolved = output.resolve()
    if resolved == ROOT or resolved in ROOT.parents:
        raise ValueError("output cannot be the source directory or one of its parents")
    if output.exists():
        if not output.is_dir() or (any(output.iterdir()) and not (output / MARKER).is_file()):
            raise ValueError("refusing to replace a non-build directory")
        shutil.rmtree(output)
    output.mkdir(parents=True)
    (output / MARKER).write_text("Generated by scripts/build.py\n", encoding="utf-8")
    for name, (_, content) in sorted(files.items()):
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    (output / "404.html").write_text(fallback_page(mappings), encoding="utf-8")
    links = "\n".join(
        f'<li><a href="{html.escape(project["target_base"], quote=True)}">'
        f'{html.escape(project["prefix"])}</a></li>' for project in projects
    )
    (output / "index.html").write_text(document(
        "Meta open source documentation",
        '<h1>Meta open source documentation</h1>\n'
        '<p>Documentation previously hosted on facebook.github.io has moved. '
        'Choose a project, or follow your original link to reach the corresponding page.</p>\n'
        f"<ul>\n{links}\n</ul>\n",
    ), encoding="utf-8")
    for asset in ("redirect.js", "style.css"):
        shutil.copyfile(ROOT / "assets" / asset, output / asset)
    (output / ".nojekyll").touch()
    (output / "robots.txt").write_text("User-agent: *\nAllow: /\n", encoding="utf-8")
    stats = {"projects": len(projects), "routes": route_count, "redirect_files": len(files)}
    (output / "build-report.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "sites.json")
    parser.add_argument("--output", type=Path, default=ROOT / "_site")
    args = parser.parse_args()
    print(json.dumps(build(args.config, args.output), sort_keys=True))


if __name__ == "__main__":
    main()
