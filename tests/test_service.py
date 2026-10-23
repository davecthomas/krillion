import itertools
import threading

import pytest

from krillion import judge as ai_judge
from krillion import service, voices
from krillion.live import ROUNDS, LiveGames

counter = itertools.count()


def propose(count, avoid):
    # Each call invents new categories, plus one repeat of something already asked
    # and one rewording, which must both be rejected.
    fresh = [{"prompt": f"Name a thing {next(counter)}", "noun": "thing"} for _ in range(count)]
    repeats = [{"prompt": avoid[0]}, {"prompt": avoid[0] + " please"}] if avoid else []
    return repeats + fresh


def similarity(prompt, others):
    # Stand-in for embeddings: a rewording of an asked prompt counts as a duplicate.
    return 0.95 if any(prompt == o + " please" for o in others) else 0.1


def catalog_for(entry):
    return {"slug": entry["slug"], "prompt": entry["prompt"], "answers": [
        {"id": "common", "name": "Common thing", "aliases": [], "tier": 0},
        {"id": "obscure", "name": "Obscure thing", "aliases": [], "tier": 5},
    ]}


@pytest.fixture
def games(tmp_path):
    gate = threading.Event()
    gate.set()

    def build(entry):
        gate.wait(5)
        return catalog_for(entry)

    g = LiveGames(propose, build, similarity, root=tmp_path, workers=2)
    g.gate = gate
    service.use(g)
    yield g
    service.use(None)


def wait_ready(g, slug):
    for _ in range(100):
        if g.status(slug) == "ready":
            return
        threading.Event().wait(0.02)
    raise AssertionError(f"{slug} never built")


def test_every_game_is_new_and_nothing_repeats(games):
    seen = set()
    for _ in range(5):
        prompts = [p["prompt"] for p in service.dive()["prompts"]]
        assert len(prompts) == ROUNDS
        assert not seen & set(prompts), "a category was asked twice"
        seen |= set(prompts)


def test_history_survives_a_restart(games, tmp_path):
    first = {p["prompt"] for p in service.dive()["prompts"]}
    again = LiveGames(propose, catalog_for, similarity, root=tmp_path)
    service.use(again)
    second = {p["prompt"] for p in service.dive()["prompts"]}
    assert not first & second


def test_ai_judge_scores_answers_while_the_catalog_builds(games, monkeypatch):
    games.gate.clear()  # hold catalog builds
    slug = service.dive()["prompts"][0]["slug"]
    assert service.reveal(slug) == {"pending": True}
    monkeypatch.setattr(ai_judge, "judge", lambda prompt, alts: {"name": "Real thing", "tier": 3})
    hit = service.judge(slug, ["real thing"])["hit"]
    assert hit["method"] == "judge" and hit["tier"] == 3
    games.gate.set()


def test_catalog_answers_and_reveal_once_built(games, monkeypatch):
    slug = service.dive()["prompts"][0]["slug"]
    wait_ready(games, slug)
    monkeypatch.setattr(ai_judge, "judge", lambda prompt, alts: None)
    assert service.judge(slug, ["obscure thing"])["hit"]["method"] == "exact"
    assert service.judge(slug, ["nonsense"])["hit"] is None
    r = service.reveal(slug)
    assert r["krillion"] == ["Obscure thing"] and r["top"] == ["Common thing"]


def test_unknown_categories_are_rejected(games):
    with pytest.raises(KeyError):
        service.judge("never-generated", ["x"])


def test_voice_choices_are_validated():
    assert voices.resolve("puck", "GB") == ("Puck", "gb")
    assert voices.resolve(None, None) == (voices.DEFAULT_VOICE, voices.DEFAULT_ACCENT)
    for bad in [("Nobody", "us"), ("Puck", "fr"), ("../x", "us")]:
        with pytest.raises(KeyError):
            voices.resolve(*bad)
