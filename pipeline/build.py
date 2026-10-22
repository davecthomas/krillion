"""Catalog pipeline: generate -> verify -> score -> tier.

    uv run python -m pipeline.build propose --count 12   # AI proposes categories into data/categories.json
    uv run python -m pipeline.build build --limit 5      # build catalogs for categories not built yet
    uv run python -m pipeline.build build --only name-a-cheese --force

Review data/categories.json between the two steps: set "enabled": false on
any proposal you don't want.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import re
from pathlib import Path

from wordfreq import zipf_frequency

from krillion.normalize import key, slugify, words
from krillion.tiers import TIER_NAMES, Signals, assign_tiers, commonness

from . import generate, similar, wiki

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CATEGORIES = DATA / "categories.json"
CATALOG = DATA / "catalog"
log = logging.getLogger("pipeline")


def _load_categories() -> list[dict]:
    return json.loads(CATEGORIES.read_text()) if CATEGORIES.exists() else []


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")


def cmd_propose(count: int) -> None:
    cats = _load_categories()
    # Random, but weighted toward topics people read about: draw 200, keep the 40 most viewed.
    pool = wiki.random_articles(200)
    views = wiki.pageviews(pool)
    seeds = sorted(pool, key=lambda t: -views.get(t, 0))[:40]
    new = generate.propose_categories(count, [c["prompt"] for c in cats], seeds)
    embed = similar.Embeddings()
    for c in new:
        slug = slugify(c.prompt)
        twin, score = similar.closest(c.prompt, [x["prompt"] for x in cats], embed)
        if score >= similar.DUPLICATE_AT or any(x["slug"] == slug for x in cats):
            print(f"  - {c.prompt}  (duplicate of {twin!r}, {score:.2f})")
            continue
        cats.append({"slug": slug, "prompt": c.prompt, "noun": c.noun, "domain": c.domain, "seed": c.seed,
                     "estimated_answers": c.estimated_answers, "enabled": True})
        print(f"  + {c.prompt}  ({c.domain}, ~{c.estimated_answers}; seed: {c.seed})")
    _save_json(CATEGORIES, cats)


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


def build_category(cat: dict) -> dict:
    noun = cat["noun"]
    answers = _merge(generate.generate_answers(generate.Category(
        cat.get("seed", ""), cat["prompt"], noun, cat.get("domain", ""), cat.get("estimated_answers", 0))))
    log.info("%s: %d answers after merge", cat["prompt"], len(answers))

    # Verify: the model's title first, then the bare name, then "Name (noun)".
    candidates = []
    for a in answers:
        n = _title_case(a["name"])
        a["_try"] = [t for t in (a.get("wikipedia_title"), f"{n} ({noun})", n) if t]
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


def cmd_build(limit: int | None, only: str | None, force: bool) -> None:
    cats = [c for c in _load_categories() if c.get("enabled", True)]
    if only:
        cats = [c for c in cats if c["slug"] == only]
    todo = [c for c in cats if force or not (CATALOG / f"{c['slug']}.json").exists()]
    for cat in todo[:limit]:
        doc = build_category(cat)
        _save_json(CATALOG / f"{cat['slug']}.json", doc)
        counts = [sum(1 for a in doc["answers"] if a["tier"] == t) for t in range(6)]
        print(f"  {cat['prompt']}: {len(doc['answers'])} verified answers ({len(doc['unverified'])} set aside), tiers {counts}")
    _save_json(CATALOG / "index.json", sorted(
        ({"slug": p.stem, "prompt": json.loads(p.read_text())["prompt"]}
         for p in CATALOG.glob("*.json") if p.name != "index.json"), key=lambda c: c["slug"]))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for noisy in ("httpx", "httpcore", "openai", "ai_api_unified"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("propose")
    p.add_argument("--count", type=int, default=12)
    b = sub.add_parser("build")
    b.add_argument("--limit", type=int)
    b.add_argument("--only")
    b.add_argument("--force", action="store_true")
    args = ap.parse_args()
    if args.cmd == "propose":
        cmd_propose(args.count)
    else:
        cmd_build(args.limit, args.only, args.force)


if __name__ == "__main__":
    main()
