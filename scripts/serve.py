"""A small, local approximation of GitHub Pages URL resolution for tests."""
from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit


class PagesHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlsplit(self.path)
        decoded = unquote(parsed.path)
        # SimpleHTTPRequestHandler safely resolves traversal within its root.
        target = Path(self.translate_path(parsed.path))
        # An extensionless route resolves foo.html before foo/index.html.
        if not decoded.endswith("/") and not target.is_file():
            html_file = Path(str(target) + ".html")
            if html_file.is_file():
                self.path = parsed.path + ".html" + ("?" + parsed.query if parsed.query else "")
        target = Path(self.translate_path(urlsplit(self.path).path))
        if target.is_file() or target.is_dir():
            return super().do_GET()
        fallback = Path(self.directory) / "404.html"
        body = fallback.read_bytes()
        self.send_response(404)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("_site"))
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), partial(PagesHandler, directory=str(args.directory)))
    print(f"Serving Pages approximation on http://127.0.0.1:{server.server_port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
