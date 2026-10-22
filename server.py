"""Local dev server: the game page from public/ plus the JSON API.

    uv run python server.py            # http://localhost:8000
    uv run python server.py --port 9000

Speech recognition needs a secure origin, and localhost counts as one, so the
microphone works here without HTTPS.
"""

from __future__ import annotations

import argparse
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from krillion import service

PUBLIC = Path(__file__).resolve().parent / "public"
MAX_BODY = 8_192


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC), **kwargs)

    def _json(self, status: int, data: dict) -> None:
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if url.path == "/api/dive":
                recent = [r for r in q.get("recent", "").split(",") if r][:100]
                return self._json(200, service.dive(q.get("mode", "practice"), q.get("date"), recent))
            if url.path == "/api/reveal":
                return self._json(200, service.reveal(q.get("slug", "")))
        except KeyError:
            return self._json(404, {"error": "unknown category"})
        if url.path.startswith("/api/"):
            return self._json(404, {"error": "not found"})
        return super().do_GET()

    def do_POST(self):
        if urlparse(self.path).path != "/api/judge":
            return self._json(404, {"error": "not found"})
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self._json(413, {"error": "too large"})
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            return self._json(200, service.judge(str(body.get("slug", "")), list(body.get("alts", []))))
        except KeyError:
            return self._json(404, {"error": "unknown category"})
        except (ValueError, TypeError):
            return self._json(400, {"error": "bad request"})

    def log_message(self, fmt, *args):
        if "/api/" in (args[0] if args else ""):
            super().log_message(fmt, *args)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    print(f"Krillion on http://localhost:{args.port}")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
