"""Game logic behind the HTTP API, kept free of any web framework so the local
dev server and a future Vercel deployment can share it.

Questions come from the bank (bank.py): built offline, never generated at
play time. The AI judge only sees answers the list can't settle.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from . import judge as ai_judge
from . import ladder
from .bank import QuestionBank
from .match import Matcher
from .tiers import KRILLION, PLANKTON

_bank: QuestionBank | None = None


def bank() -> QuestionBank:
    global _bank
    if _bank is None:
        _bank = QuestionBank()
    return _bank


def use(b: QuestionBank | None) -> None:
    """Swap in a bank (tests point one at a temporary directory)."""
    global _bank
    _bank = b


@lru_cache(maxsize=256)
def _load(path: str, mtime: float) -> tuple[dict, Matcher, dict]:
    doc = json.loads(Path(path).read_text())
    by_id = {a["id"]: a for a in doc["answers"]}
    return doc, Matcher((a["id"], [a["name"], *a["aliases"]]) for a in doc["answers"]), by_id


def catalog(slug: str) -> tuple[dict, Matcher, dict]:
    """KeyError if the question is not in the bank."""
    path = bank().catalog_path(slug)
    return _load(str(path), path.stat().st_mtime)


def prompt(slug: str) -> str:
    return bank().meta(slug)["prompt"]


def dive() -> dict:
    """A new game of questions nobody here has played."""
    return bank().take()


def judge(slug: str, alts: list[str]) -> dict:
    """Catalog first (exact, typo, sound); the AI judge for anything it can't settle."""
    alts = [a for a in alts if isinstance(a, str) and a.strip()][:5]
    q = prompt(slug)  # KeyError for unknown questions
    doc, matcher, by_id = catalog(slug)
    answers = doc["answers"]
    m = matcher.match(alts)
    if m:
        a = by_id[m.entry_id]
        rank = next(i for i, x in enumerate(answers) if x["id"] == a["id"])
        return {"hit": {"id": a["id"], "name": a["name"], "tier": a["tier"], "method": m.method,
                        "ladder": ladder.build(answers, rank=rank)}}
    j = ai_judge.judge(q, alts) if alts else None
    if not j:
        return {"hit": None}
    # Not on the list, but valid: it still gets a place in its tier
    return {"hit": {"id": None, "name": j["name"], "tier": j["tier"], "method": "judge",
                    "ladder": ladder.build(answers, tier=j["tier"])}}


def reveal(slug: str) -> dict:
    """Every One in a Krillion answer and every top answer."""
    doc, _, _ = catalog(slug)
    answers = doc["answers"]  # most common first
    krill = [a["name"] for a in answers if a["tier"] == KRILLION][::-1]
    top = [a["name"] for a in answers if a["tier"] == PLANKTON]
    return {"pending": False, "krillion": krill or [answers[-1]["name"]], "top": top or [answers[0]["name"]]}


def ladder_for(slug: str, answer_id: str | None = None, tier: int | None = None) -> dict:
    """A question's ranking ladder after the fact, for a skipped question
    (tier samples only) or a late fill."""
    doc, _, _ = catalog(slug)
    answers = doc["answers"]
    rank = next((i for i, a in enumerate(answers) if a["id"] == answer_id), None) if answer_id else None
    if rank is not None:
        lad = ladder.build(answers, rank=rank)
    elif tier is not None:
        lad = ladder.build(answers, tier=tier)
    else:
        lad = ladder.build(answers)
    return {"pending": False, "ladder": lad}
