from krillion.tiers import DEEP_CUT, KRILLION, PLANKTON, TOO_CLEVER, Signals, assign_tiers, commonness, percentiles


def test_percentiles_average_ties_and_skip_missing():
    assert percentiles([10, 20, 20, None, 30]) == [0.0, 0.5, 0.5, None, 1.0]


def test_missing_pageviews_falls_back_to_other_signals():
    s = [Signals(None, 3.0, 5, False, False), Signals(100, 1.0, 1, False, True), Signals(10_000, 2.0, 3, False, True)]
    c = commonness(s)
    assert c[0] > c[2] > c[1]


def test_phrases_lean_less_on_word_frequency():
    # Same zipf rank; the phrase gets less credit for it, so its other signals dominate.
    s = [Signals(10, 5.0, 1, True, True), Signals(10, 5.0, 1, False, True), Signals(1000, 1.0, 5, False, True)]
    c = commonness(s)
    assert c[0] < c[1]


def test_tiers_run_common_to_rare_and_krillion_must_be_verified():
    n = 100
    scores = [1 - i / n for i in range(n)]  # index 0 most common
    verified = [True] * n
    verified[-1] = False  # the least common answer has no Wikipedia article
    tiers = assign_tiers(scores, verified)
    assert tiers[:6] == [PLANKTON] * 6
    assert tiers[-1] == DEEP_CUT  # unverified never pays top points
    assert tiers.count(KRILLION) == 3 and all(tiers[i] == KRILLION for i in (96, 97, 98))
    assert TOO_CLEVER not in tiers  # filled from player data only
