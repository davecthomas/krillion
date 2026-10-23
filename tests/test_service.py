import json
import random

import pytest

from krillion import judge as ai_judge
from krillion import service
from krillion.bank import ROUNDS, BankEmpty, QuestionBank


def question(n: int, domain: str = "things") -> dict:
    return {"slug": f"name-a-thing-{n}", "prompt": f"Name a thing {n}", "domain": domain, "answers": [
        {"id": "common", "name": f"Common thing {n}", "aliases": ["usual thing"], "tier": 0},
        {"id": "obscure", "name": f"Obscure thing {n}", "aliases": [], "tier": 5},
    ]}


@pytest.fixture
def bank(tmp_path):
    qdir = tmp_path / "questions"
    qdir.mkdir()
    for n in range(20):
        (qdir / f"name-a-thing-{n}.json").write_text(json.dumps(question(n, domain=f"d{n % 4}")))
    b = QuestionBank(questions=qdir, live=tmp_path / "live", rng=random.Random(1), packages=None)
    service.use(b)
    yield b
    service.use(None)


def test_every_game_is_new_and_nothing_repeats(bank):
    seen = set()
    for _ in range(2):
        prompts = [p["prompt"] for p in service.dive()["prompts"]]
        assert len(prompts) == ROUNDS
        assert not seen & set(prompts), "a question was asked twice"
        seen |= set(prompts)
    assert bank.remaining() == 20 - 2 * ROUNDS


def test_a_game_spreads_across_domains(bank):
    slugs = [p["slug"] for p in service.dive()["prompts"]]
    assert {bank.meta(s)["domain"] for s in slugs} == {"d0", "d1", "d2", "d3"}


def test_asked_list_survives_a_restart(bank, tmp_path):
    first = {p["slug"] for p in service.dive()["prompts"]}
    again = QuestionBank(questions=bank.questions, live=tmp_path / "live", packages=None)
    service.use(again)
    second = {p["slug"] for p in service.dive()["prompts"]}
    assert not first & second


def test_an_exhausted_bank_says_so(bank):
    service.dive()
    service.dive()
    assert len(service.dive()["prompts"]) == 6  # a short game beats no game
    with pytest.raises(BankEmpty):
        service.dive()


def test_catalog_answers_are_matched_without_ai(bank, monkeypatch):
    monkeypatch.setattr(ai_judge, "judge", lambda prompt, alts: pytest.fail("judge must not run"))
    slug = service.dive()["prompts"][0]["slug"]
    n = slug.rsplit("-", 1)[1]
    hit = service.judge(slug, [f"common thing {n}"])["hit"]
    assert hit["id"] == "common" and hit["method"] == "exact"
    assert service.reveal(slug)["krillion"] == [f"Obscure thing {n}"]


def test_off_list_answers_go_to_the_judge(bank, monkeypatch):
    monkeypatch.setattr(ai_judge, "judge", lambda prompt, alts: {"name": "Real thing", "tier": 3})
    slug = service.dive()["prompts"][0]["slug"]
    hit = service.judge(slug, ["real thing"])["hit"]
    assert hit["method"] == "judge" and hit["tier"] == 3 and hit["ladder"]["total"] == 2


def test_unknown_question_is_a_key_error(bank):
    with pytest.raises(KeyError):
        service.judge("name-a-ghost", ["boo"])
