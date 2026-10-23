"""Verify answers against English Wikipedia and measure attention.

- resolve(): map candidate titles to real articles, 50 per request, following
  redirects and rejecting disambiguation pages.
- popular_seeds(): random seeds from the daily most-read lists of US and
  Canadian readers.
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


TOP = "https://wikimedia.org/api/rest_v1/metrics/pageviews/top-per-country"
_NOT_ARTICLES = ("Main_Page", "Special:", "Wikipedia:", "Portal:", "File:", "Help:", "Talk:", "User:", "-")
# Players are North American. The global English list leans toward whichever
# country reads most that day (often India), so seeds come from the US and
# Canadian lists, weighted roughly by population.
SEED_COUNTRIES = (("US", 0.85), ("CA", 0.15))


def popular_seeds(n: int = 50, days: int = 3, rng=None) -> list[str]:
    """Random seeds that lean toward topics North Americans know: sample n
    English Wikipedia articles from the most-viewed lists of a few random days
    in the last two years, each day from US or Canadian readers. One request
    per day, cached, so this takes about a second."""
    import random

    rng = rng or random.Random()
    latest = dt.date.today() - dt.timedelta(days=2)  # the newest day can lag
    countries, weights = zip(*SEED_COUNTRIES)
    pool: set[str] = set()
    for _ in range(days):
        day = latest - dt.timedelta(days=rng.randrange(730))
        country = rng.choices(countries, weights)[0]
        data = get_json(f"{TOP}/{country}/all-access/{day:%Y/%m/%d}")
        for item in (data.get("items") or [{}])[0].get("articles", []):
            title = item["article"]
            if item.get("project") == "en.wikipedia" and not title.startswith(_NOT_ARTICLES):
                pool.add(title.replace("_", " "))
    return rng.sample(sorted(pool), min(n, len(pool)))


def _window(today: dt.date | None = None) -> tuple[str, str]:
    today = today or dt.date.today()
    end = today.replace(day=1) - dt.timedelta(days=1)  # last day of previous month
    start = (end.replace(day=1) - dt.timedelta(days=330)).replace(day=1)
    return start.strftime("%Y%m%d00"), end.strftime("%Y%m%d00")


def pageviews(titles: list[str], workers: int = 8) -> dict[str, int]:
    start, end = _window()

    def one(title: str) -> tuple[str, int]:
        data = get_json(f"{PAGEVIEWS}/{quote(title.replace(' ', '_'), safe='')}/monthly/{start}/{end}")
        return title, sum(item["views"] for item in data.get("items", []))

    unique = list(dict.fromkeys(titles))
    with ThreadPoolExecutor(workers) as ex:
        return dict(ex.map(one, unique))
