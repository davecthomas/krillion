"""Game logic behind the HTTP API, kept free of any web framework so the local
dev server and a future Vercel deployment can share it.

Every game's categories are generated live (see live.py); nothing here reads
a fixed question list.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from . import judge as ai_judge
from .live import LiveGames, NotReady, default_games
from .match import Matcher
from .tiers import KRILLION, PLANKTON

_games: LiveGames | None = None


def games() -> LiveGames:
    global _games
    if _games is None:
        _games = default_games()
    return _games


def use(g: LiveGames) -> None:
    """Swap in a LiveGames (tests use stubs that make no network calls)."""
    global _games
    _games = g


@lru_cache(maxsize=128)
def _load(path: str, mtime: float) -> tuple[dict, Matcher, dict]:
    doc = json.loads(Path(path).read_text())
    by_id = {a["id"]: a for a in doc["answers"]}
    return doc, Matcher((a["id"], [a["name"], *a["aliases"]]) for a in doc["answers"]), by_id


def catalog(slug: str) -> tuple[dict, Matcher, dict]:
    """KeyError if unknown or failed, NotReady while it is being built."""
    path = games().catalog_path(slug)
    return _load(str(path), path.stat().st_mtime)


def prompt(slug: str) -> str:
    return games().meta(slug)["prompt"]


def dive() -> dict:
    """A new game of freshly generated categories."""
    return games().take()


def judge(slug: str, alts: list[str]) -> dict:
    """Catalog first (exact, typo, sound); the AI judge for anything it can't settle."""
    alts = [a for a in alts if isinstance(a, str) and a.strip()][:5]
    q = prompt(slug)  # KeyError for unknown categories
    try:
        _, matcher, by_id = catalog(slug)
        m = matcher.match(alts)
        if m:
            a = by_id[m.entry_id]
            return {"hit": {"id": a["id"], "name": a["name"], "tier": a["tier"], "method": m.method}}
    except (NotReady, KeyError):
        pass
    j = ai_judge.judge(q, alts) if alts else None
    if not j:
        return {"hit": None}
    return {"hit": {"id": None, "name": j["name"], "tier": j["tier"], "method": "judge"}}


def reveal(slug: str) -> dict:
    """Every One in a Krillion answer and every top answer, or pending while
    the catalog is still being built."""
    prompt(slug)
    try:
        doc, _, _ = catalog(slug)
    except NotReady:
        return {"pending": True}
    except KeyError:
        return {"pending": False, "krillion": [], "top": []}
    answers = doc["answers"]  # most common first
    krill = [a["name"] for a in answers if a["tier"] == KRILLION][::-1]
    top = [a["name"] for a in answers if a["tier"] == PLANKTON]
    return {"pending": False, "krillion": krill or [answers[-1]["name"]], "top": top or [answers[0]["name"]]}
