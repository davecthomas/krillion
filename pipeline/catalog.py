"""Package raw questions into the bank the game reads.

    uv run python -m pipeline.catalog          # questions not built yet
    uv run python -m pipeline.catalog --all    # everything, after a scoring change
    uv run python -m pipeline.catalog name-a-breed-of-dog

A raw question (data/catalog/raw/<slug>.json, written by the /krillion-catalog
skill) holds a prompt and answers grouped by how likely people are to say
them. Packaging is deterministic and uses no AI:

1. Verify every answer on Wikipedia ("Name (noun)", "Name", "Name noun"),
   following redirects, taking the first article whose short description is
   about the noun. Answers with no such article are set aside.
2. Add members the writer missed, from the question's Wikipedia category tree
   and from Wikidata instances of its class, keeping only those whose title
   or short description mentions the noun. These arrive with the lowest
   salience, which is where good One in a Krillion answers come from.
3. Aliases from the redirects pointing at each article.
4. Signals: Wikipedia pageviews, wordfreq, Wikidata sitelinks, Google Books
   Ngram on the 150 best-known answers, and Google Trends on the forty
   best-known.
5. Score and tier (krillion/tiers.py), then write data/catalog/questions/<slug>.json.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import logging
import re
import sys
from pathlib import Path

from wordfreq import zipf_frequency

from krillion.normalize import key, slugify, words
from krillion.tiers import TIER_NAMES, Signals, assign_tiers, commonness

from . import categories, signals, wiki, wikidata

log = logging.getLogger("pipeline")

ROOT = Path(__file__).resolve().parent.parent / "data" / "catalog"
RAW, QUESTIONS = ROOT / "raw", ROOT / "questions"
SALIENCE = {"very_common": 5, "common": 4, "known": 3, "uncommon": 2, "obscure": 1}
EXTRA_SALIENCE = 1  # members the writer did not list
MAX_EXTRA = 400  # cap on added members, so one huge category can't swamp a question
TRENDS_TOP = 40
NGRAM_TOP = 150
_PAREN = re.compile(r"\s*\([^)]*\)\s*")


def _title_case(name: str) -> str:
    return name[:1].upper() + name[1:]


def _answers(raw: dict) -> list[dict]:
    """The writer's answers, one per distinct name, best salience kept."""
    by_key: dict[str, dict] = {}
    for group, salience in SALIENCE.items():
        for name in raw.get("answers", {}).get(group, []):
            name = name.strip()
            k = key(name)
            if not k:
                continue
            if k in by_key:
                by_key[k]["salience"] = max(by_key[k]["salience"], salience)
            else:
                by_key[k] = {"name": name, "aliases": [], "salience": salience, "source": "writer"}
    return list(by_key.values())


# A member whose short description says it is one of these is a page about
# the topic, not a member of it: a book on knots, a famous dog, knot theory.
_OFF_TOPIC = re.compile(r"\b(book|novel|film|movie|album|song|band|video game|episode|magazine|website|company|"
                        r"organization|organisation|museum|person|people|actor|actress|singer|footballer|player|"
                        r"politician|racehorse|mathematics|mathematical|theory|invariant|theorem|individual|"
                        r"famous|celebrity|mascot|character|fictional|list|lists|"
                        r"star|stars|galaxy|galaxies|nebula|cluster|exoplanet|planet|supernova|quasar)\b",
                        re.IGNORECASE)


def _forms(word: str) -> set[str]:
    return {word, word + "s", word + "es", word[:-1] + "ies" if word.endswith("y") else word}


def _on_topic(title: str, description: str, noun: str) -> bool:
    """True when the title or short description uses every word of the noun
    ("dog breed" needs both "dog" and "breed", so "Sadie: dog that won
    Westminster" fails), and the description does not mark it as a page about
    the topic. The noun itself ("Knot") is the topic, not a member."""
    if key(_PAREN.sub(" ", title)) in {key(f) for f in _forms(noun)}:
        return False
    if _OFF_TOPIC.search(description):
        return False
    text = set(words(title)) | set(words(description))
    return all(text & _forms(w) for w in words(noun))


# Descriptions of things that are clearly not a member of any game category:
# places, people, organizations and works. "Cheddar" the village, "Goa" the
# state and "Third Reich" (Nazi Germany) all match.
_OTHER_MEANING = re.compile(
    r"\b(village|town|city|state|county|region|commune|municipality|province|district|capital|country|"
    r"island|river|neighbo(u)?rhood|suburb|borough|parish|department|prefecture|territory|kingdom|empire|"
    r"politician|actor|actress|singer|rapper|footballer|player|businessman|businesswoman|writer|author|"
    r"poet|painter|musician|band|album|song|film|television series|tv series|novel|book|magazine|"
    r"newspaper|website|political party|organization|organisation|surname|given name|disambiguation)\b",
    re.IGNORECASE)


def _plausible(title: str, description: str, noun: str) -> bool:
    """The writer's answer landed on an article about the noun: the title or
    short description uses a word of the noun ("Strategy board game")."""
    text = set(words(title)) | set(words(description))
    return any(text & _forms(w) for w in words(noun))


_PLACE = re.compile(r"\b(?:city|town|municipality|village|community) in (.+)$", re.IGNORECASE)


def _place(noun: str) -> str | None:
    """"Kentucky" for "city in Kentucky": the place every answer must be in."""
    m = _PLACE.search(noun)
    return m.group(1).strip() if m else None


def _in_place(title: str, description: str, place: str) -> bool:
    text = set(words(title)) | set(words(description))
    return all(w in text for w in words(place))


def _tries(name: str, noun: str) -> list[str]:
    """Article titles to look up for a writer's answer, best first. A city is
    titled "Paris, Kentucky"; a breed often "Dorset sheep"."""
    n = _title_case(name)
    place = _place(noun)
    if place:
        return list(dict.fromkeys([f"{n}, {place}", n]))
    first, short = noun.split()[0], noun.split()[-1]
    return list(dict.fromkeys([f"{n} ({noun})", f"{n} ({short})", f"{n} ({first})", n, f"{n} {first}", f"{n} {noun}"]))


def _pick_article(tries: list[str], resolved: dict[str, str], desc: dict[str, str], noun: str) -> str | None:
    """First candidate whose description names the noun; failing that, the
    first that is not clearly something else (a place, person or work).
    Broad categories need the fallback: Wikipedia calls most vegetables
    "Species of plant", never "vegetable"."""
    found = [resolved[t] for t in tries if t in resolved]
    place = _place(noun)
    if place:
        # "Paris" alone is Paris, France: a town counts only if it is in the place
        return next((art for art in found if _in_place(art, desc.get(art, ""), place)), None)
    for art in found:
        if _plausible(art, desc.get(art, ""), noun):
            return art
    for art in found:
        if not _OTHER_MEANING.search(desc.get(art, "")):
            return art
    return None


def _extra_members(raw: dict, noun: str, known: set[str]) -> list[dict]:
    """Members from the Wikipedia category and the Wikidata class that the
    writer did not list. A category tree strays ("Category:Knots" holds knot
    theory and books about knots), so a member stays only when its title or
    Wikipedia short description mentions the noun. Titles are turned into
    spoken names by dropping any parenthetical."""
    titles: set[str] = set()
    cat = raw.get("wikipedia_category")
    if cat:
        titles |= categories.members(cat if cat.startswith("Category:") else f"Category:{cat}")
    cls = raw.get("wikidata_class")
    if cls:
        titles |= set(wikidata.members(cls))
    titles -= known
    desc = wiki.descriptions(sorted(titles))
    known_keys = {key(k) for k in known}
    out = []
    for title in sorted(titles):
        if not _on_topic(title, desc.get(title, ""), noun):
            continue
        name = _PAREN.sub(" ", title).strip()
        # Catalog designations ("HD 128294", "NGC 712") are not names anyone says.
        if not name or len(words(name)) > 5 or key(name) in known_keys or re.search(r"\d", name):
            continue
        out.append({"name": name, "aliases": [], "salience": EXTRA_SALIENCE, "source": "data", "article": title})
    if len(out) > MAX_EXTRA:
        # Keep the best-known: the ones with the most Wikipedia language editions.
        links = wikidata.sitelinks([a["article"] for a in out])
        out.sort(key=lambda a: -links.get(a["article"], 0))
        log.warning("%s: %d extra members, keeping the %d best known", raw["prompt"], len(out), MAX_EXTRA)
        out = out[:MAX_EXTRA]
    return out


def package(raw: dict, *, use_trends: bool = True, extras: bool = False) -> dict:
    noun = raw["noun"]
    answers = _answers(raw)
    log.info("%s: %d answers from the writer", raw["prompt"], len(answers))

    # Verify: "Pointer (dog breed)", "Puli (dog)", then "Pointer", then "Swiss cheese".
    candidates = []
    for a in answers:
        a["_try"] = _tries(a["name"], noun)
        candidates += a["_try"]
    resolved = wiki.resolve(candidates)
    # A bare name often lands on another meaning: "Cheddar" is a village,
    # "Goa" a state, "Third Reich" redirects to Nazi Germany. Take the first
    # candidate whose short description is about the noun.
    desc = wiki.descriptions(sorted(set(resolved.values())))
    for a in answers:
        a["article"] = _pick_article(a.pop("_try"), resolved, desc, noun)

    known_articles = {a["article"] for a in answers if a["article"]}
    known_names = {a["name"] for a in answers}
    # Off by default: category trees stray into dishes, companies, schools
    # and paintings, and an added member lands in the rarest tier, where it
    # pays the most. The writer's list is the answer list.
    extra = _extra_members(raw, noun, known_articles | known_names) if extras else []
    log.info("%s: %d members added from Wikipedia and Wikidata", raw["prompt"], len(extra))
    answers += extra

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

    articles = [a["article"] for a in answers]
    redirects = wiki.redirect_aliases(articles)
    views = wiki.pageviews(articles)
    links = wikidata.sitelinks(articles)

    # Redirects are crowd-sourced aliases, but never let one steal another answer's name.
    primary = {key(a["name"]) for a in answers}
    for a in answers:
        own = {key(a["name"]), *(key(x) for x in a["aliases"])}
        add = []
        for r in redirects.get(a["article"], []):
            r = _PAREN.sub(" ", r).strip()
            k = key(r)
            if len(k) < 3 or len(words(r)) > 5 or k in own or k in primary:
                continue
            own.add(k)
            add.append(r)
        art = _PAREN.sub(" ", a["article"]).strip()
        if key(art) not in own and key(art) not in primary:
            add.append(art)
        a["aliases"] = sorted({x.strip() for x in a["aliases"] if key(x) and key(x) != key(a["name"])} | set(add))

    # "Mouse (knot)", "Brittany (dog)", "Newfoundland dog": the article title
    # is the spoken name plus more words, so the name alone means something
    # else, and its frequency in text, books and searches belongs to that
    # meaning. Those three signals are left out for it. A title in other
    # words ("Quercus macrocarpa" for bur oak) says nothing about the name.
    def ambiguous(a: dict) -> bool:
        name, art = set(words(a["name"])), set(words(a["article"]))
        return name != art and name < art

    clear = [a for a in answers if not ambiguous(a)]
    by_views = sorted(clear, key=lambda a: -(views.get(a["article"]) or 0))
    # Obscure names almost never appear in books, and Ngram is throttled, so
    # ask only about the best-known; the rest drop the signal.
    grams = signals.ngram([a["name"] for a in by_views[:NGRAM_TOP]])
    # Trends is slow and throttled: ask only about the best-known answers,
    # which is where it tells Plankton from Schooler.
    trend: dict[str, float | None] = {}
    if use_trends and clear:
        top = by_views[:TRENDS_TOP]
        trend = signals.trends([a["name"] for a in top], anchor=top[0]["name"])

    sig = [
        Signals(
            pageviews=views.get(a["article"]),
            zipf=None if ambiguous(a) else zipf_frequency(a["name"], "en"),
            salience=a["salience"],
            multiword=len(words(a["name"])) > 1,
            verified=True,
            sitelinks=links.get(a["article"]),
            ngram=grams.get(a["name"]),
            trends=trend.get(a["name"]),
        )
        for a in answers
    ]
    scores = commonness(sig)
    tiers = assign_tiers(scores, [s.verified for s in sig])

    ids: set[str] = set()
    out = []
    for a, s, c, t in sorted(zip(answers, sig, scores, tiers), key=lambda x: -x[2]):
        eid = slugify(a["name"]) or "answer"
        while eid in ids:
            eid += "-x"
        ids.add(eid)
        out.append({
            "id": eid, "name": a["name"], "aliases": a["aliases"], "article": a["article"],
            "tier": t, "tier_name": TIER_NAMES[t], "commonness": round(c, 4), "source": a["source"],
            "signals": {"pageviews": s.pageviews, "zipf": None if s.zipf is None else round(s.zipf, 2), "salience": s.salience,
                        "sitelinks": s.sitelinks, "ngram": s.ngram, "trends": s.trends},
        })
    return {
        "slug": raw["slug"], "prompt": raw["prompt"], "noun": noun, "domain": raw.get("domain", ""),
        "built_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "answers": out,
        # No Wikipedia article: not playable, since some are made up. The answer
        # judge may still accept one at play time.
        "unverified": unverified,
    }


def load_raw(path: Path) -> dict:
    raw = json.loads(path.read_text())
    raw.setdefault("slug", path.stem)
    if raw["slug"] != slugify(raw["prompt"]):
        raise ValueError(f"{path.name}: file name must be the prompt's slug, {slugify(raw['prompt'])}")
    return raw


def _in_shard(slug: str, shard: tuple[int, int] | None) -> bool:
    """Stable split of the questions across parallel build processes."""
    if not shard:
        return True
    i, n = shard
    return int(hashlib.sha1(slug.encode()).hexdigest(), 16) % n == i


def build(slugs: list[str] | None = None, *, rebuild: bool = False, use_trends: bool = True,
          shard: tuple[int, int] | None = None, extras: bool = False) -> list[str]:
    QUESTIONS.mkdir(parents=True, exist_ok=True)
    done = []
    for path in sorted(RAW.glob("*.json")):
        if slugs and path.stem not in slugs:
            continue
        if not _in_shard(path.stem, shard):
            continue
        target = QUESTIONS / path.name
        if target.exists() and not rebuild and target.stat().st_mtime >= path.stat().st_mtime:
            continue
        raw = load_raw(path)
        doc = package(raw, use_trends=use_trends, extras=extras)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=0))
        tmp.replace(target)
        done.append(raw["slug"])
        print(f"{raw['prompt']}: {len(doc['answers'])} answers, {len(doc['unverified'])} unverified")
    return done


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slugs", nargs="*", help="only these questions")
    ap.add_argument("--all", action="store_true", help="rebuild questions that are already built")
    ap.add_argument("--no-trends", action="store_true", help="skip Google Trends (faster)")
    ap.add_argument("--shard", help="i/n: build only this process's share, for parallel builds (make JOBS=n)")
    ap.add_argument("--extras", action="store_true",
                    help="also add members from the Wikipedia category and Wikidata class (noisy)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, stream=sys.stderr)
    shard = tuple(int(x) for x in args.shard.split("/")) if args.shard else None
    built = build(args.slugs or None, rebuild=args.all, use_trends=not args.no_trends, shard=shard, extras=args.extras)
    print(f"{len(built)} question(s) built")


if __name__ == "__main__":
    main()
