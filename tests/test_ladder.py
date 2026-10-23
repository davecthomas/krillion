from krillion import ladder
from krillion.tiers import DEEP_CUT, KRILLION, PLANKTON, RARE, SCHOOLER

# 20 answers, most common first, tiers in rank order
TIERS = [PLANKTON] * 3 + [SCHOOLER] * 5 + [RARE] * 6 + [DEEP_CUT] * 4 + [KRILLION] * 2
ANSWERS = [{"name": f"a{i}", "tier": t} for i, t in enumerate(TIERS)]


def names(lad):
    return [r["name"] for r in lad["rows"]]


def test_on_list_answer_slots_between_its_neighbors():
    lad = ladder.build(ANSWERS, rank=10, per_tier=2, around=2)  # a10, a Rare answer
    assert lad["rank"] == 11 and lad["total"] == 20
    assert "a10" not in names(lad)  # the page inserts the player's own answer
    above, below = names(lad)[: lad["position"]], names(lad)[lad["position"]:]
    assert above[-2:] == ["a8", "a9"] and below[:2] == ["a11", "a12"]


def test_every_tier_is_represented_in_rank_order():
    lad = ladder.build(ANSWERS, rank=4, per_tier=2)
    tiers = [r["tier"] for r in lad["rows"]]
    assert set(tiers) == {PLANKTON, SCHOOLER, RARE, DEEP_CUT, KRILLION}
    assert tiers == sorted(tiers)
    assert names(lad)[-2:] == ["a18", "a19"]  # the rarest krillion answers


def test_judged_answer_goes_mid_tier_without_a_rank():
    lad = ladder.build(ANSWERS, tier=DEEP_CUT)
    assert lad["rank"] is None
    slot_neighbor_above = lad["rows"][lad["position"] - 1]
    assert slot_neighbor_above["tier"] in (RARE, DEEP_CUT)
    assert lad["rows"][lad["position"]]["tier"] == DEEP_CUT


def test_question_with_no_answer_gets_tier_samples_only():
    lad = ladder.build(ANSWERS)
    assert lad["position"] is None and lad["rank"] is None
    assert {r["tier"] for r in lad["rows"]} == {PLANKTON, SCHOOLER, RARE, DEEP_CUT, KRILLION}


def test_top_and_bottom_ranks():
    assert ladder.build(ANSWERS, rank=0)["position"] == 0
    last = ladder.build(ANSWERS, rank=19)
    assert last["position"] == len(last["rows"])
    assert ladder.build([], rank=0) is None
