"""Turn per-answer signals into a commonness score and a tier.

Every signal becomes a percentile within its category before blending, so
pageviews (millions), Zipf scores (0-8) and salience (1-5) are comparable and
one category's scale never leaks into another.

Weights are a starting point. Player answer counts will replace them as the
ground truth once there is enough play.
"""

from __future__ import annotations

from dataclasses import dataclass

# Tier indexes shared with the game client.
PLANKTON, TOO_CLEVER, SCHOOLER, RARE, DEEP_CUT, KRILLION = range(6)
TIER_NAMES = ["Plankton", "Too Clever", "Schooler", "Rare", "Deep Cut", "One in a Krillion"]
TIER_POINTS = [10, 15, 30, 60, 85, 100]

WEIGHTS = {"pageviews": 0.40, "zipf": 0.25, "salience": 0.35}
# wordfreq scores a phrase from its separate words, so "wife carrying" looks
# common. Trust it far less for multi-word names.
ZIPF_WEIGHT_MULTIWORD = 0.08

PLANKTON_SHARE, PLANKTON_MIN = 0.06, 3
SCHOOLER_UNTIL = 0.35
RARE_UNTIL = 0.70
KRILLION_SHARE, KRILLION_MAX = 0.03, 5


@dataclass
class Signals:
    pageviews: int | None  # None when no verified article
    zipf: float
    salience: int
    multiword: bool
    verified: bool


def percentiles(values: list[float | None]) -> list[float | None]:
    """Rank-based percentile in [0, 1], ties averaged; None stays None."""
    present = sorted((v, i) for i, v in enumerate(values) if v is not None)
    out: list[float | None] = [None] * len(values)
    n = len(present)
    if n == 1:
        out[present[0][1]] = 0.5
        return out
    j = 0
    while j < n:
        k = j
        while k + 1 < n and present[k + 1][0] == present[j][0]:
            k += 1
        pct = ((j + k) / 2) / (n - 1)
        for m in range(j, k + 1):
            out[present[m][1]] = pct
        j = k + 1
    return out


def commonness(signals: list[Signals]) -> list[float]:
    pv = percentiles([s.pageviews for s in signals])
    zf = percentiles([s.zipf for s in signals])
    sl = percentiles([float(s.salience) for s in signals])
    out = []
    for s, p, z, l in zip(signals, pv, zf, sl):
        parts = []
        if p is not None:
            parts.append((WEIGHTS["pageviews"], p))
        parts.append((ZIPF_WEIGHT_MULTIWORD if s.multiword else WEIGHTS["zipf"], z))
        parts.append((WEIGHTS["salience"], l))
        total = sum(w for w, _ in parts)
        out.append(sum(w * v for w, v in parts) / total)
    return out


def assign_tiers(scores: list[float], verified: list[bool]) -> list[int]:
    """Most common first: Plankton, Schooler, Rare, Deep Cut. The least
    common *verified* answers become One in a Krillion, so an answer the model
    may have made up can never pay top points. Too Clever stays empty until
    player data shows which rare-on-paper answers players actually give."""
    n = len(scores)
    order = sorted(range(n), key=lambda i: -scores[i])
    tiers = [DEEP_CUT] * n
    plankton = max(PLANKTON_MIN, round(PLANKTON_SHARE * n))
    for rank, i in enumerate(order):
        frac = rank / n
        if rank < plankton:
            tiers[i] = PLANKTON
        elif frac < SCHOOLER_UNTIL:
            tiers[i] = SCHOOLER
        elif frac < RARE_UNTIL:
            tiers[i] = RARE
    want = min(KRILLION_MAX, max(1, round(KRILLION_SHARE * n)))
    for i in reversed(order):
        if want == 0:
            break
        if verified[i] and tiers[i] == DEEP_CUT:
            tiers[i] = KRILLION
            want -= 1
    return tiers
