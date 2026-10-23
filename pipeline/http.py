"""Polite, cached HTTP for the data sources.

Wikimedia asks for a descriptive User-Agent with contact details. Each host
gets its own minimum spacing between requests, shared by every build process:
the Wikipedia Action API, the pageviews API and the Wikidata query service
all rate-limit bursts, and Google's Ngram endpoint blocks fast scrapers.
Everything caches to disk, and a 429 pauses every process for that host.
"""

from __future__ import annotations

import fcntl
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
# Spacing per host, shared by every build process on this machine (make
# JOBS=n): Wikipedia answers bursts from one address with 429s for minutes.
INTERVALS_S = {"en.wikipedia.org": 0.4, "wikimedia.org": 0.15, "query.wikidata.org": 0.5, "books.google.com": 0.3}
CLOCKS = Path(__file__).resolve().parent / ".cache" / "clock"

_client = httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=90.0, follow_redirects=True)
_lock = threading.Lock()


def _throttle(host: str) -> None:
    """Wait for this host's turn. The last request time lives in a locked
    file, so parallel build processes share one pace."""
    interval = INTERVALS_S.get(host)
    if not interval:
        return
    CLOCKS.mkdir(parents=True, exist_ok=True)
    with _lock, open(CLOCKS / host, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        try:
            last = float(f.read() or 0)
        except ValueError:
            last = 0.0
        wait = last + interval - time.time()
        if wait > 0:
            time.sleep(wait)
        f.seek(0)
        f.truncate()
        f.write(str(time.time()))


def _pause(host: str, seconds: float) -> None:
    """Hold every process's next request to this host for `seconds`: after a
    429, one job waiting while the others keep asking only extends the block."""
    CLOCKS.mkdir(parents=True, exist_ok=True)
    with _lock, open(CLOCKS / host, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        try:
            last = float(f.read() or 0)
        except ValueError:
            last = 0.0
        # _throttle waits until last + interval, so push last forward
        until = time.time() + seconds - INTERVALS_S[host]
        if until > last:
            f.seek(0)
            f.truncate()
            f.write(str(until))


def get_json(url: str, params: dict | None = None, *, cache: bool = True):
    req = _client.build_request("GET", url, params=params)
    full = str(req.url)
    path = CACHE_DIR / hashlib.sha1(full.encode()).hexdigest()
    if cache and path.exists():
        return json.loads(path.read_text())
    host = urlsplit(full).hostname or ""
    for attempt in range(10):
        _throttle(host)
        try:
            r = _client.send(req)
        except httpx.TransportError:
            # A dropped or reset connection: wait and try again
            time.sleep(min(2 ** attempt, 30))
            continue
        if r.status_code == 429 or r.status_code >= 500:
            retry = min(float(r.headers.get("retry-after") or 2 ** attempt), 60)
            if host in INTERVALS_S:
                _pause(host, retry)  # the next _throttle waits it out
            else:
                time.sleep(retry)
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
