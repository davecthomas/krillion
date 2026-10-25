"""All-time high scores: a top 10 per scoring mode, kept in
data/live/highscores.json beside the asked-list.

A score is accepted only for a game the bank started, once per game, and
never above what that game's questions can pay, so a replayed or hand-made
request can't put itself on the board.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
import uuid
from pathlib import Path

LIVE = Path(__file__).resolve().parent.parent / "data" / "live"
MODES = ("rare", "popular")
SIZE = 10
MAX_NAME = 16
# The best answer pays 100, plus up to 50% for speed
MAX_PER_QUESTION = 150


class ScoreRejected(ValueError):
    """The submission can't go on the board (unknown or repeated game, bad mode, impossible score)."""


def clean_name(name: object) -> str:
    text = " ".join(str(name or "").split())
    text = "".join(c for c in text if c.isprintable())[:MAX_NAME].strip()
    return text or "Anonymous"


class HighScores:
    def __init__(self, live: Path = LIVE, size: int = SIZE):
        self.path = live / "highscores.json"
        self.size = size
        self._lock = threading.Lock()
        data = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.boards: dict[str, list[dict]] = {m: data.get("boards", {}).get(m, []) for m in MODES}
        self.games: set[str] = set(data.get("games", []))  # games already submitted

    def snapshot(self) -> dict[str, list[dict]]:
        with self._lock:
            return {m: [dict(e) for e in b] for m, b in self.boards.items()}

    def qualifies(self, mode: str, score: int) -> bool:
        board = self.boards.get(mode, [])
        return score > 0 and (len(board) < self.size or score > board[-1]["score"])

    def submit(self, game_id: str, mode: str, name: object, score: int, questions: int,
               max_questions: int) -> int | None:
        """The entry's 1-based rank, or None when it didn't make the board.
        `max_questions` is how many questions the bank gave that game."""
        if mode not in MODES:
            raise ScoreRejected("unknown mode")
        if not isinstance(score, int) or score < 0 or score > max_questions * MAX_PER_QUESTION:
            raise ScoreRejected("impossible score")
        if not isinstance(questions, int) or not 0 <= questions <= max_questions:
            raise ScoreRejected("impossible question count")
        with self._lock:
            if game_id in self.games:
                raise ScoreRejected("this game's score is already in")
            self.games.add(game_id)
            rank = None
            if self.qualifies(mode, score):
                entry = {"name": clean_name(name), "score": score, "questions": questions,
                         "date": dt.date.today().isoformat(), "game": game_id}
                board = self.boards[mode]
                # Ties keep the earlier score first
                rank = next((i for i, e in enumerate(board) if score > e["score"]), len(board))
                board.insert(rank, entry)
                del board[self.size:]
                rank += 1
            self._save()
        return rank

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps({"boards": self.boards, "games": sorted(self.games)}, indent=1)
        tmp = self.path.with_name(f"highscores.{uuid.uuid4().hex}.tmp")
        tmp.write_text(data)
        tmp.replace(self.path)
