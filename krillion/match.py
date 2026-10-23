"""Match a typed or spoken answer to a catalog entry.

Cheapest first, and each stage only runs when the one before it missed:

1. exact     normalized key or alias, with naive plurals
2. typo      Damerau-Levenshtein (a swap counts as one edit), allowance
             scaled by length
3. sound     Double Metaphone codes, for speech-recognition mishearings
             such as "grew air" for gruyère

Stages 2 and 3 never guess between two entries: a fuzzy hit is accepted only
when it is closer than the best hit for any other entry. Anything still
unmatched is left to the caller (an AI judge, then the miss list).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from metaphone import doublemetaphone
from rapidfuzz.distance import DamerauLevenshtein

from .normalize import key, variants, words

MAX_NGRAM = 6


@dataclass(frozen=True)
class Match:
    entry_id: str
    method: str  # "exact" | "typo" | "sound"
    distance: int = 0


def typo_allowance(length: int) -> int:
    """Edits tolerated for a key of this length. Short names sit too close
    together (Mali/Bali, Io/Ia) to forgive anything."""
    if length <= 4:
        return 0
    if length <= 8:
        return 1
    return 2


def _generic_words(names: Iterable[str]) -> frozenset[str]:
    """Words shared by many answers in a category ("cake", "hound"). They say
    nothing about which answer was meant."""
    counts: dict[str, int] = {}
    n = 0
    for name in names:
        n += 1
        for w in set(words(name)):
            counts[w] = counts.get(w, 0) + 1
    floor = max(3, 0.15 * n)
    return frozenset(w for w, c in counts.items() if c >= floor)


def _codes(k: str) -> set[str]:
    return {c for c in doublemetaphone(k) if c}


class Matcher:
    """Index of one category's answers. Build once, match many times."""

    def __init__(self, entries: Iterable[tuple[str, Iterable[str]]]):
        # entries: (entry_id, [name, alias, alias, ...])
        self.exact: dict[str, str] = {}
        self.fuzzy: list[tuple[str, str]] = []  # (distinctive key, entry_id)
        self.sound: dict[str, list[tuple[str, str]]] = {}  # code -> [(key, entry_id)]

        entries = [(eid, list(names)) for eid, names in entries]
        self.generic = _generic_words(names[0] for _, names in entries if names)
        canonical: dict[str, str] = {}
        for entry_id, names in entries:
            for name in names:
                k = key(name)
                if not k:
                    continue
                for i, v in enumerate(variants(k)):
                    # A real name beats a guessed singular of another entry.
                    if i == 0:
                        if v in canonical and canonical[v] != entry_id:
                            continue  # first entry to claim a key keeps it
                        canonical[v] = entry_id
                        self.exact[v] = entry_id
                    else:
                        self.exact.setdefault(v, entry_id)
                d = self._distinct(words(name))
                if d:
                    self.fuzzy.append((d, entry_id))
                    for c in _codes(d):
                        self.sound.setdefault(c, []).append((d, entry_id))

    def _distinct(self, ws: list[str]) -> str:
        return "".join(w for w in ws if w not in self.generic)

    # -- stages ---------------------------------------------------------

    def _ngrams(self, text: str) -> list[tuple[str, list[str]]]:
        w = words(text)
        out = []
        for i in range(len(w)):
            for n in range(min(MAX_NGRAM, len(w) - i), 0, -1):
                out.append(("".join(w[i : i + n]), w[i : i + n]))
        # Longest first, so "blue cheese" wins over "blue".
        out.sort(key=lambda g: len(g[0]), reverse=True)
        return out

    def _exact(self, grams) -> Match | None:
        for g, _ in grams:
            for v in variants(g):
                hit = self.exact.get(v)
                if hit:
                    return Match(hit, "exact")
        return None

    def _best_per_entry(self, scored: Iterable[tuple[str, int]]) -> list[tuple[int, str]]:
        best: dict[str, int] = {}
        for entry_id, d in scored:
            if d < best.get(entry_id, 1 << 30):
                best[entry_id] = d
        return sorted((d, e) for e, d in best.items())

    def _unique(self, ranked: list[tuple[int, str]]) -> tuple[int, str] | None:
        if not ranked:
            return None
        if len(ranked) > 1 and ranked[1][0] == ranked[0][0]:
            return None  # a tie between two entries: don't guess
        return ranked[0]

    def _typo(self, grams) -> Match | None:
        # Measure typos on the distinctive words only. "coffee cake" and
        # "joffre cake" share "cake", which would otherwise earn the pair a
        # two-edit allowance though coffee and joffre are different words.
        for _, ws in grams:
            g = self._distinct(ws)
            allow = typo_allowance(len(g))
            if not allow:
                continue
            scored = []
            for k, entry_id in self.fuzzy:
                if abs(len(k) - len(g)) > allow:
                    continue
                # Both sides must be long enough to deserve the allowance.
                limit = min(allow, typo_allowance(len(k)))
                if not limit:
                    continue
                d = DamerauLevenshtein.distance(g, k, score_cutoff=limit)
                if d <= limit:
                    scored.append((entry_id, d))
            hit = self._unique(self._best_per_entry(scored))
            if hit:
                return Match(hit[1], "typo", hit[0])
        return None

    def _sound(self, grams) -> Match | None:
        for _, ws in grams:
            g = self._distinct(ws)
            if len(g) < 3:
                continue
            scored = []
            for c in _codes(g):
                for code, pairs in self._sound_candidates(c):
                    for k, entry_id in pairs:
                        spelled = DamerauLevenshtein.distance(g, k)
                        # A short code like "PL" fits too many words (blue, pule,
                        # pail); demand the spelling be close too.
                        if len(code) < 3 and spelled > 1:
                            continue
                        scored.append((entry_id, spelled))
            hit = self._unique(self._best_per_entry(scored))
            if hit:
                return Match(hit[1], "sound", hit[0])
        return None

    def _sound_candidates(self, c: str):
        if c in self.sound:
            yield c, self.sound[c]
        if len(c) >= 6:  # long codes may differ by one sound (xolo: S vs X)
            for code, pairs in self.sound.items():
                if code != c and abs(len(code) - len(c)) <= 1 and DamerauLevenshtein.distance(code, c, score_cutoff=1) <= 1:
                    yield code, pairs

    # -- public ---------------------------------------------------------

    def match(self, text: str | Iterable[str]) -> Match | None:
        """Match one answer, or a list of recognizer alternatives (best first)."""
        alts = [text] if isinstance(text, str) else list(text)
        gram_lists = [self._ngrams(a) for a in alts if a and a.strip()]
        for stage in (self._exact, self._typo, self._sound):
            for grams in gram_lists:
                hit = stage(grams)
                if hit:
                    return hit
        return None
