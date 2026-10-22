from krillion import service


def test_daily_dive_is_the_same_all_day():
    a = service.dive("daily", "2026-10-22")
    b = service.dive("daily", "2026-10-22")
    assert a["prompts"] == b["prompts"]


def test_practice_skips_recent_categories_while_fresh_ones_remain():
    pool = service.slugs()
    recent = pool[:-1]  # everything but one was just played
    d = service.dive("practice", recent=recent)
    slugs = [p["slug"] for p in d["prompts"]]
    assert pool[-1] in slugs
    assert len(slugs) == len(set(slugs)) == min(service.ROUNDS, len(pool))


def test_reveal_lists_every_krillion_answer():
    r = service.reveal(service.slugs()[0])
    assert isinstance(r["krillion"], list) and r["krillion"]
    assert isinstance(r["top"], list) and r["top"]
