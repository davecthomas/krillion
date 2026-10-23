"""Polite, cached HTTP for the data sources.

Wikimedia asks for a descriptive User-Agent with contact details. Each host
gets its own minimum spacing between requests: the Wikipedia Action API and
the Wikidata query service rate-limit bursts, and Google's Ngram endpoint
blocks fast scrapers. The pageviews REST API takes parallel requests.
Everything caches to disk and backs off on 429.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

USER_AGENT = "krillion-catalog/0.1 (https://github.com/davecthomas/krillion)"
CACHE_DIR = Path(__file__).resolve().parent / ".cache" / "http"
INTERVALS_S = {"en.wikipedia.org": 0.12, "query.wikidata.org": 0.5, "books.google.com": 1.5}

_client = httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=90.0, follow_redirects=True)
_lock = threading.Lock()
_last: dict[str, float] = {}


def _throttle(host: str) -> None:
    interval = INTERVALS_S.get(host)
    if not interval:
        return
    with _lock:
        wait = _last.get(host, 0.0) + interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last[host] = time.monotonic()


def get_json(url: str, params: dict | None = None, *, cache: bool = True):
    req = _client.build_request("GET", url, params=params)
    full = str(req.url)
    path = CACHE_DIR / hashlib.sha1(full.encode()).hexdigest()
    if cache and path.exists():
        return json.loads(path.read_text())
    host = urlsplit(full).hostname or ""
    for attempt in range(6):
        _throttle(host)
        try:
            r = _client.send(req)
        except httpx.TransportError:
            # A dropped or reset connection: wait and try again
            time.sleep(min(2 ** attempt, 30))
            continue
        if r.status_code == 429 or r.status_code >= 500:
            retry = float(r.headers.get("retry-after") or 2 ** attempt)
            time.sleep(min(retry, 60))
            continue
        if r.status_code == 404:
            data = {}
        else:
            r.raise_for_status()
            data = r.json()
        if cache:
            # Parallel builds share this cache: write whole files only.
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
            tmp.write_text(json.dumps(data))
            tmp.replace(path)
        return data
    raise RuntimeError(f"gave up after repeated rate limiting: {full}")
