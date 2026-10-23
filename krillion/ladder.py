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
          per_tier: int = 2, around: int = 2) -> dict | None:
    """Ladder for one graded answer.

    rank: the answer's index in `answers` (it is on the list). It is left out of
          the rows: the page inserts the player's own answer at `position`.
    tier: for an answer only the AI judge accepted, which has no rank; it goes
          in the middle of its tier.
    """
    n = len(answers)
    if not n or (rank is None and tier is None):
        return None
    on_list = rank is not None
    if not on_list:
        in_tier = [i for i, a in enumerate(answers) if a["tier"] == tier]
        if in_tier:
            rank = in_tier[len(in_tier) // 2]
        else:  # no answers in that tier: place it before the first rarer one
            rank = next((i for i, a in enumerate(answers) if a["tier"] > tier), n)

    picks: set[int] = set()
    for t in LADDER_TIERS:
        idx = [i for i, a in enumerate(answers) if a["tier"] == t]
        # The best-known answers of each tier; for One in a Krillion, the rarest
        picks.update(idx[-per_tier:] if t == KRILLION else idx[:per_tier])
    picks.update(range(max(0, rank - around), min(n, rank + around + (1 if on_list else 0))))
    if on_list:
        picks.discard(rank)

    rows = [{"name": answers[i]["name"], "tier": answers[i]["tier"], "rank": i + 1} for i in sorted(picks)]
    position = sum(1 for i in picks if i < rank)
    return {"rows": rows, "position": position, "rank": rank + 1 if on_list else None, "total": n}
