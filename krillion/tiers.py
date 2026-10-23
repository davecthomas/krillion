"""Turn per-answer signals into a commonness score and a tier.

Every signal becomes a percentile within its category before blending, so
pageviews (millions), Zipf scores (0-8), sitelink counts and salience (1-5)
are comparable and one category's scale never leaks into another. A signal
that is missing for an answer drops out of that answer's blend.

Weights are a starting point. Player answer counts will replace them as the
ground truth once there is enough play.
"""

from __future__ import annotations

from dataclasses import dataclass

# Tier indexes shared with the game client.
PLANKTON, TOO_CLEVER, SCHOOLER, RARE, DEEP_CUT, KRILLION = range(6)
TIER_NAMES = ["Plankton", "Too Clever", "Schooler", "Rare", "Deep Cut", "One in a Krillion"]
TIER_POINTS = [10, 15, 30, 60, 85, 100]

WEIGHTS = {
    "pageviews": 0.30,  # Wikipedia pageviews, 12 months
    "zipf": 0.15,  # wordfreq
    "salience": 0.20,  # the writer's guess
    "sitelinks": 0.10,  # how many Wikipedia languages have the article
    "ngram": 0.10,  # Google Books, American English
    "trends": 0.15,  # Google Trends, US
}
# wordfreq scores a phrase from its separate words, so "wife carrying" looks
# common. Trust it far less for multi-word names.
ZIPF_WEIGHT_MULTIWORD = 0.05
# The build asks Ngram and Trends about the best-known answers only, so a
# value there is a rank among the top few. It is placed in the top band of
# the whole list; otherwise Los Angeles, mid-pack among big cities on
# Ngram, sinks below Sacramento, which was never asked.
TOP_ONLY = ("ngram", "trends")

PLANKTON_SHARE, PLANKTON_MIN = 0.06, 3
SCHOOLER_UNTIL = 0.35
RARE_UNTIL = 0.70
KRILLION_SHARE, KRILLION_MAX = 0.03, 5


@dataclass
class Signals:
    pageviews: int | None  # None when no verified article
    zipf: float | None  # None for an ambiguous word, whose frequency belongs to another meaning
    salience: int
    multiword: bool
    verified: bool
    sitelinks: int | None = None
    ngram: float | None = None
    trends: float | None = None


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
    cols = {
        name: percentiles([getattr(s, name) if getattr(s, name) is None else float(getattr(s, name))
                           for s in signals])
        for name in WEIGHTS
    }
    n = len(signals)
    for name in TOP_ONLY:
        col = cols[name]
        share = sum(v is not None for v in col) / n if n else 1.0
        cols[name] = [None if v is None else 1 - share + share * v for v in col]
    out = []
    for i, s in enumerate(signals):
        parts = []
        for name, weight in WEIGHTS.items():
            v = cols[name][i]
            if v is None:
                continue
            if name == "zipf" and s.multiword:
                weight = ZIPF_WEIGHT_MULTIWORD
            parts.append((weight, v))
        total = sum(w for w, _ in parts)
        out.append(sum(w * v for w, v in parts) / total if total else 0.5)
    return out


def assign_tiers(scores: list[float], verified: list[bool]) -> list[int]:
    """Most common first: Plankton, Schooler, Rare, Deep Cut. The least
    common *verified* answers become One in a Krillion, so an answer the writer
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
