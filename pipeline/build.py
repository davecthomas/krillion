"""Build one category's answer catalog: generate -> verify -> score -> tier.

Live games call build_category() for each freshly generated category; see
krillion/live.py.
"""

from __future__ import annotations

import datetime as dt
import logging
import re

from wordfreq import zipf_frequency

from krillion.normalize import key, slugify, words
from krillion.tiers import TIER_NAMES, Signals, assign_tiers, commonness

from . import generate, wiki

log = logging.getLogger("pipeline")


_PAREN = re.compile(r"\s*\([^)]*\)\s*")


def _merge(raw: list[dict]) -> list[dict]:
    """Collapse answers the model listed twice under different names."""
    by_key: dict[str, dict] = {}
    for a in raw:
        name = a["name"].strip()
        k = key(name)
        if not k:
            continue
        if k in by_key:
            by_key[k]["aliases"] += a["aliases"]
            by_key[k]["salience"] = max(by_key[k]["salience"], a["salience"])
            continue
        by_key[k] = {"name": name, "aliases": list(a["aliases"]), "wikipedia_title": a.get("wikipedia_title"),
                     "salience": min(5, max(1, int(a["salience"])))}
    return list(by_key.values())


def _title_case(name: str) -> str:
    return name[:1].upper() + name[1:]


def build_category(cat: dict, rounds: int = 2) -> dict:
    """Generate, verify, score and tier one category. Live games use one
    generation round so the catalog is ready within about a minute."""
    noun = cat["noun"]
    answers = _merge(generate.generate_answers(generate.Category(
        cat.get("seed", ""), cat["prompt"], noun, cat.get("domain", ""), cat.get("estimated_answers", 0)),
        rounds=rounds))
    log.info("%s: %d answers after merge", cat["prompt"], len(answers))

    # Verify: the model's title first, then the bare name, then "Name (noun)".
    candidates = []
    for a in answers:
        n = _title_case(a["name"])
        # The model gives bare names, so try the likely article titles in order:
        # "Pointer (dog breed)", then "Pointer", then "Swiss cheese".
        a["_try"] = [t for t in (a.get("wikipedia_title"), f"{n} ({noun})", n, f"{n} {noun}") if t]
        candidates += a["_try"]
    resolved = wiki.resolve(candidates)
    for a in answers:
        a["article"] = next((resolved[t] for t in a.pop("_try") if t in resolved), None)

    # Two answers on one article are one answer.
    by_article: dict[str, dict] = {}
    merged = []
    for a in answers:
        art = a["article"]
        if art and art in by_article:
            keep = by_article[art]
            keep["aliases"] += [a["name"], *a["aliases"]]
            keep["salience"] = max(keep["salience"], a["salience"])
            continue
        if art:
            by_article[art] = a
        merged.append(a)
    unverified = sorted(a["name"] for a in merged if not a["article"])
    answers = [a for a in merged if a["article"]]

    articles = [a["article"] for a in answers if a["article"]]
    redirects = wiki.redirect_aliases(articles)
    views = wiki.pageviews(articles)

    # Redirects are crowd-sourced aliases, but never let one steal another answer's name.
    primary = {key(a["name"]) for a in answers}
    for a in answers:
        own = {key(a["name"]), *(key(x) for x in a["aliases"])}
        extra = []
        for r in redirects.get(a["article"], []) if a["article"] else []:
            r = _PAREN.sub(" ", r).strip()
            k = key(r)
            if len(k) < 3 or len(words(r)) > 5 or k in own or k in primary:
                continue
            own.add(k)
            extra.append(r)
        if a["article"]:
            art = _PAREN.sub(" ", a["article"]).strip()
            if key(art) not in own and key(art) not in primary:
                extra.append(art)
        a["aliases"] = sorted({x.strip() for x in a["aliases"] if key(x) and key(x) != key(a["name"])} | set(extra))

    signals = [
        Signals(
            pageviews=views.get(a["article"]) if a["article"] else None,
            zipf=zipf_frequency(a["name"], "en"),
            salience=a["salience"],
            multiword=len(words(a["name"])) > 1,
            verified=a["article"] is not None,
        )
        for a in answers
    ]
    scores = commonness(signals)
    tiers = assign_tiers(scores, [s.verified for s in signals])

    ids: set[str] = set()
    out = []
    for a, s, c, t in sorted(zip(answers, signals, scores, tiers), key=lambda x: -x[2]):
        eid = slugify(a["name"]) or "answer"
        while eid in ids:
            eid += "-x"
        ids.add(eid)
        out.append({
            "id": eid, "name": a["name"], "aliases": a["aliases"], "article": a["article"],
            "tier": t, "tier_name": TIER_NAMES[t], "commonness": round(c, 4),
            "signals": {"pageviews": s.pageviews, "zipf": round(s.zipf, 2), "salience": s.salience},
        })
    return {
        "slug": cat["slug"], "prompt": cat["prompt"], "noun": noun, "domain": cat.get("domain"),
        "built_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "model": generate.GENERATION_MODEL, "answers": out,
        # No Wikipedia article: not playable, since some are made up. The answer
        # judge may still accept one at play time.
        "unverified": unverified,
    }
