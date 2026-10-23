import json

import pytest

from krillion.tiers import Signals, commonness
from pipeline import catalog


def test_writer_answers_merge_case_and_keep_best_salience():
    raw = {"answers": {"very_common": ["Bowline"], "common": [], "known": ["bowline", "Clove hitch"],
                       "uncommon": [], "obscure": ["  "]}}
    got = {a["name"]: a["salience"] for a in catalog._answers(raw)}
    assert got == {"Bowline": 5, "Clove hitch": 3}


@pytest.mark.parametrize("title, description, noun, ok", [
    ("Mudi", "Dog breed", "dog breed", True),
    ("Puli (dog)", "Hungarian breed of dog", "dog breed", True),
    ("Sadie (dog)", "Dog that won Best in Show", "dog breed", False),  # a dog, not a breed
    ("Knots Unravelled", "Book about knots", "knot", False),
    ("Knot", "Method of fastening rope", "knot", False),  # the topic itself
    ("Mouse (knot)", "Knot used to thicken rope", "knot", True),
    ("Milnor invariants", "Knot theory invariants", "knot", False),
])
def test_only_members_are_added_from_category_trees(title, description, noun, ok):
    assert catalog._on_topic(title, description, noun) is ok


def test_missing_signals_drop_out_of_the_blend():
    full = Signals(pageviews=10, zipf=4.0, salience=5, multiword=False, verified=True,
                   sitelinks=50, ngram=1e-6, trends=1.0)
    sparse = Signals(pageviews=1, zipf=None, salience=1, multiword=False, verified=True)
    a, b = commonness([full, sparse])
    assert a > b and 0.0 <= b <= 1.0


def test_raw_file_name_must_match_the_prompt(tmp_path):
    p = tmp_path / "name-a-dog.json"
    p.write_text(json.dumps({"prompt": "Name a cat", "noun": "cat", "answers": {}}))
    with pytest.raises(ValueError):
        catalog.load_raw(p)


def test_every_committed_raw_question_is_well_formed():
    paths = sorted(catalog.RAW.glob("*.json"))
    assert paths, "no raw questions committed"
    for p in paths:
        raw = catalog.load_raw(p)
        assert raw["prompt"].startswith(("Name a ", "Name an ")), p.name
        assert raw["noun"] and raw.get("domain"), p.name
        assert set(raw["answers"]) <= set(catalog.SALIENCE), p.name
        assert sum(len(v) for v in raw["answers"].values()) >= 60, p.name


@pytest.mark.parametrize("title, description, noun, ok", [
    ("Chess", "Strategy board game", "board game", True),
    ("Nazi Germany", "German state from 1933 to 1945", "board game", False),
    ("Goa", "State in India", "board game", False),
    ("Cheddar, Somerset", "Village in Somerset, England", "cheese", False),
    ("Cheddar cheese", "Hard English cheese", "cheese", True),
    ("Some article", "", "cheese", True),  # nothing to judge by
])
def test_writer_answers_must_land_on_an_article_about_the_noun(title, description, noun, ok):
    assert catalog._plausible(title, description, noun) is ok


def test_stars_and_galaxies_are_not_constellations():
    assert not catalog._on_topic("Mira", "Red giant star in the constellation Cetus", "constellation")
    assert not catalog._on_topic("Whirlpool Galaxy", "Galaxy in the constellation Canes Venatici", "constellation")
    assert catalog._on_topic("Lynx (constellation)", "Constellation in the northern celestial hemisphere",
                             "constellation")


def test_shards_split_every_question_exactly_once():
    slugs = [f"name-a-thing-{i}" for i in range(200)]
    shards = [{s for s in slugs if catalog._in_shard(s, (i, 3))} for i in range(3)]
    assert set().union(*shards) == set(slugs)
    assert sum(len(x) for x in shards) == len(slugs)
    assert all(len(x) > 40 for x in shards)  # roughly even
