"""Try answers against a built question, the way the game judges them
(list matching only; the game also asks the AI judge).

    uv run python -m pipeline.try_answers                      # list built questions
    uv run python -m pipeline.try_answers name-a-wine-grape    # type answers, blank line to quit
    uv run python -m pipeline.try_answers name-a-wine-grape "cabernet" "pinot grigo"
    uv run python -m pipeline.try_answers name-a-wine-grape --tiers   # a sample of each tier
"""

from __future__ import annotations

import json
import sys

from krillion.bank import QUESTIONS as CATALOG
from krillion.match import Matcher
from krillion.tiers import TIER_NAMES, TIER_POINTS


def load(slug: str) -> tuple[dict, Matcher, dict]:
    doc = json.loads((CATALOG / f"{slug}.json").read_text())
    by_id = {a["id"]: a for a in doc["answers"]}
    return doc, Matcher((a["id"], [a["name"], *a["aliases"]]) for a in doc["answers"]), by_id


def judge(text: str, matcher: Matcher, by_id: dict) -> str:
    m = matcher.match(text)
    if not m:
        return f"  {text!r}: no match (the AI judge would see this next)"
    a = by_id[m.entry_id]
    how = m.method if m.method == "exact" else f"{m.method}, {m.distance} edit{'s' if m.distance != 1 else ''}"
    views = a["signals"]["pageviews"]
    views = f"{views:,} views/yr" if views is not None else "no Wikipedia article"
    return (f"  {text!r} -> {a['name']}  [{TIER_NAMES[a['tier']]}, {TIER_POINTS[a['tier']]} pts]  "
            f"via {how}; {views}, salience {a['signals']['salience']}")


def show_tiers(doc: dict) -> None:
    for t, name in enumerate(TIER_NAMES):
        xs = [a["name"] for a in doc["answers"] if a["tier"] == t]
        if xs:
            step = max(1, len(xs) // 8)
            print(f"  {name} ({len(xs)}): {', '.join(xs[::step][:8])}")
    print(f"  set aside, no Wikipedia article ({len(doc['unverified'])}): {', '.join(doc['unverified'][:8])}")


def main() -> None:
    args = sys.argv[1:]
    if not args:
        for p in sorted(CATALOG.glob("*.json")):
            d = json.loads(p.read_text())
            print(f"  {p.stem:<34} {d['prompt']} ({len(d['answers'])} answers)")
        return
    doc, matcher, by_id = load(args[0])
    print(f"{doc['prompt']}: {len(doc['answers'])} answers")
    if "--tiers" in args:
        show_tiers(doc)
        return
    if len(args) > 1:
        for text in args[1:]:
            print(judge(text, matcher, by_id))
        return
    while True:
        try:
            text = input("answer> ").strip()
        except EOFError:
            break
        if not text:
            break
        print(judge(text, matcher, by_id))


if __name__ == "__main__":
    main()
