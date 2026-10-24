"""Two Google signals for how often people write or search for a name.

- Books Ngram: how often the phrase appears in American English books,
  2000-2019 (the corpus ends there). Up to 12 phrases per request. Neither
  endpoint is an official API, so both are throttled and cached, and a
  failure means a missing signal, never a failed build.
- Trends: US search interest over five years. Trends returns 0-100 relative
  to the top term in each request of up to five terms, so every request
  carries the same anchor term and scores are expressed relative to it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path

from .http import get_json

log = logging.getLogger(__name__)

NGRAM = "https://books.google.com/ngrams/json"
NGRAM_BATCH = 12


def ngram(names: list[str]) -> dict[str, float | None]:
    """Mean yearly frequency 2015-2019, or None when the phrase never appears."""
    out: dict[str, float | None] = {n: None for n in names}
    # Commas separate phrases in the query, so a name containing one can't be asked.
    askable = [n for n in names if "," not in n and len(n.split()) <= 5]
    for i in range(0, len(askable), NGRAM_BATCH):
        batch = askable[i:i + NGRAM_BATCH]
        try:
            rows = get_json(NGRAM, {"content": ",".join(batch), "year_start": 2000, "year_end": 2019,
                                    "corpus": "en-US-2019", "smoothing": 3, "case_insensitive": "true"})
        except Exception:
            log.warning("ngram lookup failed for %s", batch[:1], exc_info=True)
            continue
        for row in rows if isinstance(rows, list) else []:
            label = row.get("ngram", "")
            # Case-insensitive queries return one aggregate row per phrase, labeled "(All)".
            name = label.replace(" (All)", "")
            series = row.get("timeseries") or []
            match = next((n for n in batch if n.lower() == name.lower()), None)
            if match and series and (out[match] is None or label.endswith("(All)")):
                out[match] = sum(series[-5:]) / len(series[-5:])
    return out


TRENDS_CACHE = Path(__file__).resolve().parent / ".cache" / "trends"
MAX_FAILURES = 2  # Google rate-limits hard; after two failures in a row, stop asking for this run


def _cached(anchor: str, batch: list[str]) -> Path:
    digest = hashlib.sha1(json.dumps([anchor, *batch]).encode()).hexdigest()
    return TRENDS_CACHE / f"{digest}.json"


def trends(names: list[str], anchor: str, pause_s: float = 2.0) -> dict[str, float | None]:
    """US search interest relative to `anchor` (anchor = 1.0), or None when
    Trends has no data, is rate limiting, or pytrends is not installed.
    Answers cache to disk, so a rebuild asks Google nothing new."""
    out: dict[str, float | None] = {n: None for n in names}
    others = [n for n in names if n != anchor]
    batches = [others[i:i + 4] for i in range(0, len(others), 4)]
    out[anchor] = 1.0
    pt = None
    failures = 0
    for batch in batches:
        path = _cached(anchor, batch)
        if path.exists():
            out.update(json.loads(path.read_text()))
            continue
        if failures >= MAX_FAILURES:
            continue
        if pt is None:
            try:
                from pytrends.request import TrendReq
            except ImportError:
                log.warning("pytrends not installed: skipping the Trends signal")
                return out
            pt = TrendReq(hl="en-US", tz=300, timeout=(10, 30), retries=0)
        try:
            pt.build_payload([anchor, *batch], timeframe="today 5-y", geo="US")
            df = pt.interest_over_time()
        except Exception as e:
            failures += 1
            log.warning("trends lookup failed (%s): %s", type(e).__name__, batch[:1])
            if failures >= MAX_FAILURES:
                log.warning("Google Trends is rate limiting: skipping it for the rest of this question")
            time.sleep(pause_s * 5)
            continue
        failures = 0
        got: dict[str, float | None] = {n: None for n in batch}
        if not df.empty and anchor in df and float(df[anchor].mean()) > 0:
            base = float(df[anchor].mean())
            got = {n: float(df[n].mean()) / base if n in df else None for n in batch}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(got))
        out.update(got)
        time.sleep(pause_s)
    return out
