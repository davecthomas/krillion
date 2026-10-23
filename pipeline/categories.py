"""Members of an English Wikipedia category tree.

Editors curate these by hand, so "Category:Potato dishes" lists dishes and
little else. Two levels of subcategories cover regional and type splits
("Category:Fried potato") without wandering off topic the way deeper levels
do. Pages that describe the topic itself ("Potato", "List of potato dishes")
are dropped by title shape.
"""

from __future__ import annotations

import re

from .http import get_json

API = "https://en.wikipedia.org/w/api.php"
_META = re.compile(r"^(List|Lists|Index|Outline|Glossary|Timeline|History|Comparison) of |"
                   r"^(Category|Template|Portal|Wikipedia):|\bby (country|year|decade|type|region|century)\b", re.IGNORECASE)
_SKIP_SUBCAT = re.compile(r"\b(by |stubs|templates|lists|people|history of|images|navigational|wikiproject|"
                          r"categories|metaphors|in (popular )?culture|in fiction|terminology)\b", re.IGNORECASE)


def _page(cmtitle: str) -> list[dict]:
    out: list[dict] = []
    params = {"action": "query", "list": "categorymembers", "cmtitle": cmtitle, "cmlimit": 500,
              "cmtype": "page|subcat", "format": "json"}
    while True:
        data = get_json(API, params)
        out += data.get("query", {}).get("categorymembers", [])
        if "continue" not in data:
            return out
        params = {**params, **data["continue"]}


def members(category: str, depth: int = 2, max_pages: int = 5_000) -> set[str]:
    """Article titles in the category and its subcategories, `depth` levels down."""
    titles: set[str] = set()
    seen = {category}
    frontier = [category]
    for _ in range(depth + 1):
        next_frontier = []
        for cat in frontier:
            for m in _page(cat):
                if m["ns"] == 0:
                    if not _META.search(m["title"]):
                        titles.add(m["title"])
                elif m["ns"] == 14 and m["title"] not in seen and not _SKIP_SUBCAT.search(m["title"]):
                    seen.add(m["title"])
                    next_frontier.append(m["title"])
            if len(titles) > max_pages:
                return titles
        frontier = next_frontier
    return titles
