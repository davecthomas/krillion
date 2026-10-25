import json
import random

import pytest

from krillion import service
from krillion.bank import ROUNDS, QuestionBank
from krillion.scores import MAX_PER_QUESTION, HighScores, ScoreRejected, clean_name


@pytest.fixture
def bank(tmp_path):
    qdir = tmp_path / "questions"
    qdir.mkdir()
    for n in range(40):
        doc = {"slug": f"name-a-thing-{n}", "prompt": f"Name a thing {n}", "domain": f"d{n % 4}", "answers": []}
        (qdir / f"name-a-thing-{n}.json").write_text(json.dumps(doc))
    b = QuestionBank(questions=qdir, live=tmp_path / "live", rng=random.Random(1), packages=None)
    service.use(b)
    yield b
    service.use(None)


def test_board_keeps_the_top_ten_best_first(tmp_path):
    hs = HighScores(tmp_path, size=10)
    ranks = [hs.submit(f"g{i}", "rare", f"P{i}", s, 7, 7) for i, s in enumerate([300, 900, 500] + [100] * 9)]
    assert ranks[:3] == [1, 1, 2]
    board = hs.snapshot()["rare"]
    assert [e["score"] for e in board] == [900, 500, 300] + [100] * 7
    assert board[3]["name"] == "P3"  # ties keep the earlier score first
    assert not hs.qualifies("rare", 100) and hs.qualifies("rare", 101)
    assert hs.snapshot()["popular"] == []  # modes keep separate boards


def test_boards_survive_a_restart(tmp_path):
    HighScores(tmp_path).submit("g1", "popular", "Ann", 420, 7, 7)
    again = HighScores(tmp_path)
    assert again.snapshot()["popular"][0]["name"] == "Ann"
    with pytest.raises(ScoreRejected):
        again.submit("g1", "popular", "Ann", 420, 7, 7)  # once per game, even after a restart


def test_impossible_submissions_are_rejected(tmp_path):
    hs = HighScores(tmp_path)
    with pytest.raises(ScoreRejected):
        hs.submit("g1", "rare", "X", 7 * MAX_PER_QUESTION + 1, 7, 7)
    with pytest.raises(ScoreRejected):
        hs.submit("g2", "chess", "X", 10, 7, 7)
    with pytest.raises(ScoreRejected):
        hs.submit("g3", "rare", "X", 10, 8, 7)


def test_names_are_tidied():
    assert clean_name("  Dave\n  T  ") == "Dave T"
    assert clean_name("") == clean_name(None) == "Anonymous"
    assert len(clean_name("x" * 40)) == 16


def test_only_games_the_bank_started_can_score(bank):
    with pytest.raises(ScoreRejected):
        service.submit_score("made-up", "rare", "X", 100, 7)
    game = service.dive()
    out = service.submit_score(game["id"], "rare", "Dave", 640, ROUNDS)
    assert out["rank"] == 1
    assert out["boards"]["rare"][0] == {"name": "Dave", "score": 640, "questions": ROUNDS,
                                         "date": out["boards"]["rare"][0]["date"]}  # no game id shown
    with pytest.raises(ScoreRejected):
        service.submit_score(game["id"], "rare", "Dave", 640, ROUNDS)
