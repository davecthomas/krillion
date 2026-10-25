"""The question bank: built questions on disk, and which ones have been asked.

Questions come from the committed packages in data/packages/ (unpacked into
data/catalog/questions/ on first use) plus any you have built locally. A game
draws seven questions nobody here has played yet, spread across domains, and
records them in data/live/asked.json so no question repeats until the whole
bank has been played. Nothing is generated at play time.
"""

from __future__ import annotations

import datetime as dt
import json
import random
import threading
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "data"
QUESTIONS = ROOT / "catalog" / "questions"
PACKAGES = ROOT / "packages"
LIVE = ROOT / "live"
ROUNDS = 7


class BankEmpty(Exception):
    """No built questions, or every one has been asked."""


class QuestionBank:
    def __init__(self, questions: Path = QUESTIONS, live: Path = LIVE, rounds: int = ROUNDS, rng=None,
                 packages: Path | None = PACKAGES):
        self.questions, self.rounds, self._rng = questions, rounds, rng or random.Random()
        if packages is not None and packages.exists():
            from pipeline.package import unpack

            unpack(packages, questions)
        live.mkdir(parents=True, exist_ok=True)
        self.live = live
        self._asked_path = live / "asked.json"
        self.asked: list[dict] = (
            json.loads(self._asked_path.read_text()) if self._asked_path.exists() else [])
        self._lock = threading.Lock()
        self._meta: dict[str, dict] = {}
        self.refresh()

    def refresh(self) -> None:
        """Pick up questions built since the last look."""
        meta = {}
        for path in sorted(self.questions.glob("*.json")):
            try:
                doc = json.loads(path.read_text())
                meta[doc["slug"]] = {"slug": doc["slug"], "prompt": doc["prompt"], "domain": doc.get("domain", "")}
            except (ValueError, KeyError):
                continue
        with self._lock:
            self._meta = meta

    # -- categories -----------------------------------------------------

    def meta(self, slug: str) -> dict:
        return self._meta[slug]  # KeyError: not in the bank

    def catalog_path(self, slug: str) -> Path:
        self.meta(slug)
        return self.questions / f"{slug}.json"

    def remaining(self) -> int:
        played = {a["slug"] for a in self.asked}
        return sum(1 for s in self._meta if s not in played)

    # -- games ----------------------------------------------------------

    def game_size(self, game_id: str) -> int:
        """How many questions the bank gave this game; 0 for a game it never started."""
        with self._lock:
            return sum(1 for a in self.asked if a["game"] == game_id)

    def take(self) -> dict:
        """A new game of unplayed questions, as varied in domain as the bank allows."""
        self.refresh()
        with self._lock:
            played = {a["slug"] for a in self.asked}
            pool = [m for s, m in self._meta.items() if s not in played]
            if not pool:
                raise BankEmpty("every question in the bank has been played: build more")
            self._rng.shuffle(pool)
            picked: list[dict] = []
            domains: set[str] = set()
            for m in pool:  # one per domain first, then whatever is left
                if m["domain"] not in domains:
                    picked.append(m)
                    domains.add(m["domain"])
                if len(picked) == self.rounds:
                    break
            for m in pool:
                if len(picked) == self.rounds:
                    break
                if m not in picked:
                    picked.append(m)
            game_id = uuid.uuid4().hex[:12]
            now = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
            self.asked += [{"slug": m["slug"], "game": game_id, "asked_at": now} for m in picked]
            data = json.dumps(self.asked, indent=1)
        tmp = self._asked_path.with_name(f"asked.{uuid.uuid4().hex}.tmp")
        tmp.write_text(data)
        tmp.replace(self._asked_path)
        return {"id": game_id, "prompts": [{"slug": m["slug"], "prompt": m["prompt"]} for m in picked]}
