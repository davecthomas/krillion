"""The ranking ladder shown when an answer is graded.

A catalog's answers are sorted most common first, so an answer's index is its
rank. The ladder is a short, readable slice of that order: a couple of
answers from each tier for context, plus the answers just above and below the
player's, so the spot their answer slides into is exact.
"""

from __future__ import annotations

from .tiers import DEEP_CUT, KRILLION, PLANKTON, RARE, SCHOOLER

LADDER_TIERS = (PLANKTON, SCHOOLER, RARE, DEEP_CUT, KRILLION)  # in rank order


def build(answers: list[dict], *, rank: int | None = None, tier: int | None = None,
          per_tier: int = 3, around: int = 3) -> dict | None:
    """Ladder for one graded answer.

    rank: the answer's index in `answers` (it is on the list). It is left out of
          the rows: the page inserts the player's own answer at `position`.
    tier: for an answer only the AI judge accepted, which has no rank; it goes
          in the middle of its tier.
    Neither: a question with no answer gets the tier samples only, and
          position is None.
    """
    n = len(answers)
    if not n:
        return None
    if rank is None and tier is None:
        picks = _tier_samples(answers, per_tier)
        rows = [{"name": answers[i]["name"], "tier": answers[i]["tier"], "rank": i + 1} for i in sorted(picks)]
        return {"rows": rows, "position": None, "rank": None, "total": n}
    on_list = rank is not None
    if not on_list:
        in_tier = [i for i, a in enumerate(answers) if a["tier"] == tier]
        if in_tier:
            rank = in_tier[len(in_tier) // 2]
        else:  # no answers in that tier: place it before the first rarer one
            rank = next((i for i, a in enumerate(answers) if a["tier"] > tier), n)

    picks = _tier_samples(answers, per_tier)
    picks.update(range(max(0, rank - around), min(n, rank + around + (1 if on_list else 0))))
    if on_list:
        picks.discard(rank)

    rows = [{"name": answers[i]["name"], "tier": answers[i]["tier"], "rank": i + 1} for i in sorted(picks)]
    position = sum(1 for i in picks if i < rank)
    return {"rows": rows, "position": position, "rank": rank + 1 if on_list else None, "total": n}


def _tier_samples(answers: list[dict], per_tier: int) -> set[int]:
    """The best-known answers of each tier; for One in a Krillion, the rarest."""
    picks: set[int] = set()
    for t in LADDER_TIERS:
        idx = [i for i, a in enumerate(answers) if a["tier"] == t]
        picks.update(idx[-per_tier:] if t == KRILLION else idx[:per_tier])
    return picks
