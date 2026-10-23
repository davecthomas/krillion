"""Verify answers against English Wikipedia and measure attention.

- resolve(): map candidate titles to real articles, 50 per request, following
  redirects and rejecting disambiguation pages.
- redirect_aliases(): the redirects pointing at an article, which are
  crowd-sourced alternate names ("Gruyere" -> "Gruyère cheese").
- pageviews(): human pageviews over the last 12 full months.
"""

from __future__ import annotations

import datetime as dt
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

from .http import get_json

API = "https://en.wikipedia.org/w/api.php"
PAGEVIEWS = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user"
BATCH = 50


def _query(titles: list[str], **extra) -> list[dict]:
    """Run a titles query with continuation; return each response's query block."""
    params = {
        "action": "query",
        "titles": "|".join(titles),
        "redirects": 1,
        "format": "json",
        "formatversion": 2,
        **extra,
    }
    blocks = []
    while True:
        data = get_json(API, params)
        blocks.append(data.get("query", {}))
        if "continue" not in data:
            return blocks
        params = {**params, **data["continue"]}


def resolve(candidates: list[str]) -> dict[str, str]:
    """{asked title: final article title} for titles that are real, non-disambiguation articles."""
    found: dict[str, str] = {}
    unique = list(dict.fromkeys(t for t in candidates if t))
    for i in range(0, len(unique), BATCH):
        chunk = unique[i : i + BATCH]
        mapping = {t: t for t in chunk}
        disambig: set[str] = set()
        real: set[str] = set()
        for q in _query(chunk, prop="pageprops", ppprop="disambiguation"):
            for step in ("normalized", "redirects"):
                for n in q.get(step, []):
                    for asked, cur in mapping.items():
                        if cur == n["from"]:
                            mapping[asked] = n["to"]
            for p in q.get("pages", []):
                if p.get("missing") or p.get("invalid"):
                    continue
                if "disambiguation" in (p.get("pageprops") or {}):
                    disambig.add(p["title"])
                else:
                    real.add(p["title"])
        for asked, final in mapping.items():
            if final in real and final not in disambig:
                found[asked] = final
    return found


def redirect_aliases(titles: list[str]) -> dict[str, list[str]]:
    """{article title: [redirect titles]} for main-namespace redirects."""
    out: dict[str, list[str]] = {}
    unique = list(dict.fromkeys(titles))
    for i in range(0, len(unique), BATCH):
        for q in _query(unique[i : i + BATCH], prop="redirects", rdnamespace=0, rdlimit="max"):
            for p in q.get("pages", []):
                for r in p.get("redirects", []) or []:
                    out.setdefault(p["title"], []).append(r["title"])
    return out


def random_articles(n: int = 40) -> list[str]:
    """Random main-namespace article titles: the source of surprise for new categories."""
    data = get_json(API, {"action": "query", "list": "random", "rnnamespace": 0, "rnlimit": min(n, 500),
                          "format": "json", "formatversion": 2}, cache=False)
    return [r["title"] for r in data.get("query", {}).get("random", [])]


def _window(today: dt.date | None = None) -> tuple[str, str]:
    today = today or dt.date.today()
    end = today.replace(day=1) - dt.timedelta(days=1)  # last day of previous month
    start = (end.replace(day=1) - dt.timedelta(days=330)).replace(day=1)
    return start.strftime("%Y%m%d00"), end.strftime("%Y%m%d00")


def pageviews(titles: list[str], workers: int = 4) -> dict[str, int]:
    start, end = _window()

    def one(title: str) -> tuple[str, int]:
        data = get_json(f"{PAGEVIEWS}/{quote(title.replace(' ', '_'), safe='')}/monthly/{start}/{end}")
        return title, sum(item["views"] for item in data.get("items", []))

    unique = list(dict.fromkeys(titles))
    with ThreadPoolExecutor(workers) as ex:
        return dict(ex.map(one, unique))
