"""Game logic behind the HTTP API, kept free of any web framework so the local
dev server and a future Vercel deployment can share it.

Questions come from the bank (bank.py): built offline, never generated at
play time. The AI judge only sees answers the list can't settle.
"""

from __future__ import annotations

import json
import threading
from functools import lru_cache
from pathlib import Path

from . import judge as ai_judge
from . import ladder, neighbors
from .bank import QuestionBank
from .match import Matcher
from .scores import HighScores
from .tiers import KRILLION, PLANKTON

_bank: QuestionBank | None = None
_scores: HighScores | None = None


def bank() -> QuestionBank:
    global _bank
    if _bank is None:
        _bank = QuestionBank()
    return _bank


def use(b: QuestionBank | None) -> None:
    """Swap in a bank (tests point one at a temporary directory). The high
    scores live beside its asked-list."""
    global _bank, _scores
    _bank, _scores = b, None


def scores() -> HighScores:
    global _scores
    if _scores is None:
        _scores = HighScores(bank().live)
    return _scores


def high_scores() -> dict:
    """Both boards, without the game ids."""
    return {m: [{k: v for k, v in e.items() if k != "game"} for e in board]
            for m, board in scores().snapshot().items()}


def submit_score(game_id: str, mode: str, name: object, score: object, questions: object) -> dict:
    """{"rank": 1-10 or None, "boards": ...}. ScoreRejected for a game the
    bank never started, a repeat, or an impossible score."""
    from .scores import ScoreRejected

    size = bank().game_size(str(game_id))
    if not size:
        raise ScoreRejected("unknown game")
    rank = scores().submit(str(game_id), str(mode), name, score, questions, size)
    return {"rank": rank, "boards": high_scores()}


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
    """A new game of questions nobody here has played. Each question's
    embedding shortlist is prepared in the background, so the first answer
    that needs the judge doesn't wait for it."""
    b = bank()
    game = b.take()
    paths = [b.catalog_path(p["slug"]) for p in game["prompts"]]
    threading.Thread(target=_warm, args=(paths,), daemon=True).start()
    return game


def _warm(paths: list[Path]) -> None:
    for path in paths:
        try:
            neighbors.prepare([a["name"] for a in _load(str(path), path.stat().st_mtime)[0]["answers"]])
        except Exception:
            return  # no key or no network: the shortlist simply has no neighbors


def judge(slug: str, alts: list[str]) -> dict:
    """The list first (exact, partial, typo, sound); then the AI judge, given
    a shortlist of the list answers closest to what was heard. When the judge
    names a list answer, it scores at that answer's rank and tier."""
    alts = [a for a in alts if isinstance(a, str) and a.strip()][:5]
    q = prompt(slug)  # KeyError for unknown questions
    doc, matcher, by_id = catalog(slug)
    answers = doc["answers"]
    m = matcher.match(alts)
    if m:
        return {"hit": _list_hit(answers, by_id[m.entry_id], m.method)}
    if not alts:
        return {"hit": None}
    j = ai_judge.judge(q, alts, _shortlist(doc, matcher, alts[0]))
    on_list = _on_list(matcher, j)
    if on_list and not _resembles(alts, by_id[on_list.entry_id]["name"], answers):
        # The judge snapped to a list name the player didn't say ("lychee nut"
        # as Cashew nut): judge again without the list.
        j = ai_judge.judge(q, alts)
        on_list = _on_list(matcher, j)
        if on_list and not _resembles(alts, by_id[on_list.entry_id]["name"], answers):
            on_list = None
    if not j:
        return {"hit": None}
    if on_list:
        return {"hit": _list_hit(answers, by_id[on_list.entry_id], "judge")}
    # Valid but not on the list: it still gets a place in its tier
    return {"hit": {"id": None, "name": j["name"], "tier": j["tier"], "method": "judge",
                    "ladder": ladder.build(answers, tier=j["tier"])}}


def _on_list(matcher, j: dict | None):
    m = matcher.match([j["name"]]) if j else None
    return m if m and m.method in ("exact", "partial") else None


def _resembles(alts: list[str], name: str, answers: list[dict], *, cutoff: float = 0.7) -> bool:
    """Whether what was heard could be `name` misheard or misspelled: at least
    half of the name's distinctive words (not ones many answers share, like
    "nut" or "dog") are close in spelling or sound to a heard word."""
    from rapidfuzz.distance import DamerauLevenshtein

    from .match import _codes
    from .normalize import words

    counts: dict[str, int] = {}
    for a in answers:
        for w in set(words(a["name"])):
            counts[w] = counts.get(w, 0) + 1
    heard = {w for a in alts for w in words(a)}
    target = [w for w in words(name) if counts.get(w, 0) <= 3] or words(name)
    if not heard or not target:
        return False

    def close(w: str) -> bool:
        return any(DamerauLevenshtein.normalized_similarity(w, h) >= cutoff or _codes(w) & _codes(h)
                   for h in heard)

    return sum(map(close, target)) >= max(1, (len(target) + 1) // 2)


def _list_hit(answers: list[dict], a: dict, method: str) -> dict:
    rank = next(i for i, x in enumerate(answers) if x["id"] == a["id"])
    return {"id": a["id"], "name": a["name"], "tier": a["tier"], "method": method,
            "ladder": ladder.build(answers, rank=rank)}


def _shortlist(doc: dict, matcher, heard: str, size: int = 8) -> list[str]:
    """List answers holding the heard words, then embedding neighbors."""
    by_id = {a["id"]: a["name"] for a in doc["answers"]}
    names = [by_id[e] for e in matcher.candidates(heard, size)]
    if len(names) < size:
        all_names = [a["name"] for a in doc["answers"]]
        for i in neighbors.nearest(heard, all_names, size):
            if all_names[i] not in names:
                names.append(all_names[i])
            if len(names) >= size:
                break
    return names


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
