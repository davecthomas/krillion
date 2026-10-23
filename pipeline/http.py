"""Polite, cached HTTP for Wikimedia APIs.

Wikimedia asks for a descriptive User-Agent with contact details and
rate-limits bursts, so every request goes through one client that caches to
disk, spaces requests out, and backs off on 429.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path

import httpx

USER_AGENT = "krillion-catalog/0.1 (https://github.com/davecthomas/krillion)"
CACHE_DIR = Path(__file__).resolve().parent / ".cache" / "http"
MIN_INTERVAL_S = 0.12

_client = httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30.0, follow_redirects=True)
_lock = threading.Lock()
_last = 0.0


def _throttle() -> None:
    global _last
    with _lock:
        wait = _last + MIN_INTERVAL_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last = time.monotonic()


def get_json(url: str, params: dict | None = None, *, cache: bool = True) -> dict:
    req = _client.build_request("GET", url, params=params)
    full = str(req.url)
    path = CACHE_DIR / hashlib.sha1(full.encode()).hexdigest()
    if cache and path.exists():
        return json.loads(path.read_text())
    for attempt in range(6):
        _throttle()
        r = _client.send(req)
        if r.status_code == 429 or r.status_code >= 500:
            retry = float(r.headers.get("retry-after") or 2 ** attempt)
            time.sleep(min(retry, 60))
            continue
        if r.status_code == 404:
            data: dict = {}
        else:
            r.raise_for_status()
            data = r.json()
        if cache:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data))
        return data
    raise RuntimeError(f"gave up after repeated rate limiting: {full}")
