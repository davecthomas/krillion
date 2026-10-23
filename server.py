"""Local dev server: the game page from public/ plus the JSON API.

    uv run python server.py            # http://localhost:8000
    uv run python server.py --port 9000

Speech recognition needs a secure origin, and localhost counts as one, so the
microphone works here without HTTPS.
"""

from __future__ import annotations

import argparse
import json
import logging
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from krillion import service, tts, voices

PUBLIC = Path(__file__).resolve().parent / "public"
MAX_BODY = 8_192
log = logging.getLogger("server")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC), **kwargs)

    def _send(self, status: int, body: bytes, ctype: str, cache: str = "no-store") -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", cache)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, data: dict) -> None:
        self._send(status, json.dumps(data).encode(), "application/json")

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ValueError("too large")
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if url.path == "/api/dive":
                voices.resolve(q.get("voice"), q.get("accent"))  # reject unknown voices early
                # Questions are recorded just in time: the page asks for each
                # question's clip while the player answers the one before.
                try:
                    game = service.dive()
                except Exception:
                    log.exception("generating a game failed")
                    return self._json(503, {"error": "Couldn't generate new questions. Try again in a moment."})
                return self._json(200, game)
            if url.path == "/api/reveal":
                return self._json(200, service.reveal(q.get("slug", "")))
            if url.path == "/api/ladder":
                tier = q.get("tier")
                return self._json(200, service.ladder_for(
                    q.get("slug", ""), q.get("answer") or None, int(tier) if tier and tier.isdigit() else None))
            if url.path == "/api/voices":
                return self._json(200, voices.options())
            if url.path == "/api/preview":
                voice, accent = voices.resolve(q.get("voice"), q.get("accent"))
                return self._clip(lambda: tts.record_preview(voice, accent))
            if url.path == "/api/audio":
                return self._audio(q)
        except KeyError:
            return self._json(404, {"error": "unknown category, voice or accent"})
        if url.path.startswith("/api/"):
            return self._json(404, {"error": "not found"})
        return super().do_GET()

    def _audio(self, q: dict) -> None:
        slug = q.get("slug", "")
        prompt = service.prompt(slug)  # KeyError for categories never generated here
        voice, accent = voices.resolve(q.get("voice"), q.get("accent"))
        return self._clip(lambda: tts.record(slug, prompt, voice, accent))

    def _clip(self, make) -> None:
        try:
            path = make()
        except Exception:
            log.exception("recording failed")
            return self._json(503, {"error": "voice unavailable; the page will use browser speech"})
        self._send(200, path.read_bytes(), "audio/mpeg", "public, max-age=86400")

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            body = self._body()
            if path == "/api/judge":
                return self._json(200, service.judge(str(body.get("slug", "")), list(body.get("alts", []))))
        except KeyError:
            return self._json(404, {"error": "unknown category, voice or accent"})
        except (ValueError, TypeError):
            return self._json(400, {"error": "bad request"})
        return self._json(404, {"error": "not found"})

    def end_headers(self):
        # Static files: always check for a newer version, so a reload picks up
        # changes. Unchanged files still come back as a cheap 304.
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, fmt, *args):
        if "/api/" in (args[0] if args else ""):
            super().log_message(fmt, *args)


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    service.games().prepare_next()  # generate the first game before anyone asks
    print(f"Krillion on http://localhost:{args.port}")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
