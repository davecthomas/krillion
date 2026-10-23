"""Game logic behind the HTTP API, kept free of any web framework so the local
dev server and the Vercel functions can share it."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import random
from functools import lru_cache
from pathlib import Path

from .match import Matcher
from .tiers import KRILLION, PLANKTON

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "data" / "catalog"
AUDIO = ROOT / "public" / "audio"
ROUNDS = 7


@lru_cache(maxsize=64)
def _load(slug: str, mtime: float) -> tuple[dict, Matcher, dict]:
    doc = json.loads((CATALOG / f"{slug}.json").read_text())
    by_id = {a["id"]: a for a in doc["answers"]}
    matcher = Matcher((a["id"], [a["name"], *a["aliases"]]) for a in doc["answers"])
    return doc, matcher, by_id


def catalog(slug: str) -> tuple[dict, Matcher, dict]:
    path = CATALOG / f"{slug}.json"
    if not slug.replace("-", "").isalnum() or not path.exists():
        raise KeyError(slug)
    return _load(slug, path.stat().st_mtime)


def slugs() -> list[str]:
    return sorted(p.stem for p in CATALOG.glob("*.json") if p.name != "index.json")


def dive(mode: str, date: str | None = None, recent: list[str] | None = None) -> dict:
    """Up to seven prompts. A daily dive is the same for everyone on a date.

    A practice dive is random, and skips the player's recently played
    categories (`recent`, most recent first) until it runs out of fresh ones;
    then it reuses the ones played longest ago."""
    day = date or dt.date.today().isoformat()
    pool = slugs()
    if mode == "daily":
        rng = random.Random(int(hashlib.sha256(day.encode()).hexdigest()[:12], 16))
        rng.shuffle(pool)
        picked = pool[:ROUNDS]
    else:
        rng = random.Random()
        seen = [s for s in dict.fromkeys(recent or []) if s in pool]
        fresh = [s for s in pool if s not in seen]
        rng.shuffle(fresh)
        picked = (fresh + list(reversed(seen)))[:ROUNDS]
        rng.shuffle(picked)
    return {"mode": mode, "date": day,
            "prompts": [_prompt(s) for s in picked]}


def _prompt(slug: str) -> dict:
    p = {"slug": slug, "prompt": catalog(slug)[0]["prompt"]}
    if (AUDIO / f"{slug}.mp3").exists():
        p["audio"] = f"audio/{slug}.mp3"  # recorded question; the page falls back to browser speech
    return p


def judge(slug: str, alts: list[str]) -> dict:
    """Match the recognizer's alternatives (best first) against the catalog."""
    doc, matcher, by_id = catalog(slug)
    m = matcher.match([a for a in alts if isinstance(a, str)][:5])
    if not m:
        return {"hit": None}
    a = by_id[m.entry_id]
    return {"hit": {"id": a["id"], "name": a["name"], "tier": a["tier"], "method": m.method}}


def reveal(slug: str) -> dict:
    """The answers to show when a round ends: every One in a Krillion answer
    and every top (Plankton) answer, most notable first."""
    doc, _, _ = catalog(slug)
    answers = doc["answers"]  # sorted most common first
    krill = [a["name"] for a in answers if a["tier"] == KRILLION][::-1]
    top = [a["name"] for a in answers if a["tier"] == PLANKTON]
    return {"krillion": krill or [answers[-1]["name"]], "top": top or [answers[0]["name"]]}
