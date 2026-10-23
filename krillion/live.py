"""Live games: every New dive gets categories generated for it.

There is no question bank. For each game:

1. Seeds: a random sample from Wikipedia's most-read articles on random days.
2. Propose: the AI turns seeds into categories. Any category too close to one
   asked before (embedding cosine >= 0.84, or the same wording) is dropped, so a
   question never repeats.
3. Build: each category's answer list is generated, verified and scored in the
   background (about a minute). Until it's ready, an AI judge scores answers.

The next game is prepared while the current one is played, so New dive
usually starts at once. The history of asked categories and their catalogs
live in data/live/, which is local and git-ignored.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import threading
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from .normalize import slugify

ROUNDS = 7
DUPLICATE_AT = 0.84
LIVE = Path(__file__).resolve().parent.parent / "data" / "live"
log = logging.getLogger(__name__)


class NotReady(Exception):
    """The category exists but its catalog is still being built."""


class LiveGames:
    def __init__(
        self,
        propose: Callable[[int, list[str]], list[dict]],
        build: Callable[[dict], dict],
        similarity: Callable[[str, list[str]], float],
        root: Path = LIVE,
        workers: int = 4,
    ):
        # propose(count, avoid_prompts) -> [{"prompt", "noun", "domain", "seed"}]
        # build(category) -> catalog document
        # similarity(prompt, others) -> highest cosine against others
        self._propose, self._build, self._similarity = propose, build, similarity
        self.root = root
        self.catalogs = root / "catalog"
        self.catalogs.mkdir(parents=True, exist_ok=True)
        self._history_path = root / "history.json"
        self.history: list[dict] = (
            json.loads(self._history_path.read_text()) if self._history_path.exists() else [])
        self._by_slug = {h["slug"]: h for h in self.history}
        self._status: dict[str, str] = {}
        self._ready: deque[dict] = deque()
        self._lock = threading.Lock()
        self._prep_lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="catalog")

    # -- categories -----------------------------------------------------

    def meta(self, slug: str) -> dict:
        return self._by_slug[slug]  # KeyError: never generated here

    def catalog_path(self, slug: str) -> Path:
        self.meta(slug)
        path = self.catalogs / f"{slug}.json"
        if not path.exists():
            # Only a build running in this process will ever finish. One that
            # failed, or was cut off by a restart, means there is no list.
            if self._status.get(slug) != "building":
                raise KeyError(slug)
            raise NotReady(slug)
        return path

    def status(self, slug: str) -> str:
        if (self.catalogs / f"{slug}.json").exists():
            return "ready"
        return self._status.get(slug, "unknown")

    # -- games ----------------------------------------------------------

    def take(self) -> dict:
        """A new game. Usually already prepared; otherwise generated now."""
        with self._prep_lock:  # waits for an in-flight preparation
            with self._lock:
                game = self._ready.popleft() if self._ready else None
            if game is None:
                game = self._prepare()
        self.prepare_next()
        return game

    def prepare_next(self) -> None:
        """Prepare the following game in the background."""
        def run() -> None:
            with self._prep_lock:
                with self._lock:
                    if self._ready:
                        return
                try:
                    game = self._prepare()
                except Exception:
                    log.exception("preparing the next game failed")
                    return
                with self._lock:
                    self._ready.append(game)

        threading.Thread(target=run, daemon=True, name="prepare-game").start()

    def _prepare(self) -> dict:
        asked = [h["prompt"] for h in self.history]
        proposals = self._propose(ROUNDS + 4, asked[-200:])
        picked: list[dict] = []
        for c in proposals:
            prompt = c["prompt"].strip()
            others = asked + [p["prompt"] for p in picked]
            if prompt.lower() in {o.lower() for o in others}:
                continue
            if others and self._similarity(prompt, others) >= DUPLICATE_AT:
                continue
            picked.append({**c, "prompt": prompt})
            if len(picked) == ROUNDS:
                break
        if not picked:
            raise RuntimeError("no new categories could be generated")

        game_id = uuid.uuid4().hex[:12]
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        prompts = []
        for c in picked:
            slug = base = slugify(c["prompt"])
            n = 2
            while slug in self._by_slug:
                slug, n = f"{base}-{n}", n + 1
            entry = {"slug": slug, "prompt": c["prompt"], "noun": c.get("noun", ""),
                     "domain": c.get("domain", ""), "seed": c.get("seed", ""),
                     "game": game_id, "created_at": now}
            with self._lock:
                self.history.append(entry)
                self._by_slug[slug] = entry
                self._status[slug] = "building"
            prompts.append({"slug": slug, "prompt": c["prompt"]})
        self._save_history()
        for p in prompts:  # first question first, so it is ready soonest
            self._pool.submit(self._build_one, self._by_slug[p["slug"]])
        return {"id": game_id, "prompts": prompts}

    def _build_one(self, entry: dict) -> None:
        slug = entry["slug"]
        try:
            doc = self._build(entry)
            tmp = self.catalogs / f"{slug}.tmp"
            tmp.write_text(json.dumps(doc, ensure_ascii=False))
            tmp.replace(self.catalogs / f"{slug}.json")
            self._status[slug] = "ready"
        except Exception:
            log.exception("building %s failed", slug)
            self._status[slug] = "failed"

    def _save_history(self) -> None:
        with self._lock:
            data = json.dumps(self.history, indent=1, ensure_ascii=False)
        # A unique temp name: two writers (threads or processes) must never share one.
        tmp = self._history_path.with_name(f"history.{uuid.uuid4().hex}.tmp")
        tmp.write_text(data)
        tmp.replace(self._history_path)


def default_games() -> LiveGames:
    """LiveGames wired to the real pipeline: OpenAI via ai-api-unified, Wikipedia."""
    from pipeline import build, generate, similar, wiki

    from .cache_store import install

    install()  # ai-api-unified's response cache, persisted to data/cache/

    embed = similar.Embeddings()
    embed_lock = threading.Lock()

    def propose(count: int, avoid: list[str]) -> list[dict]:
        seeds = wiki.popular_seeds(50)
        return [c.__dict__ for c in generate.propose_categories(count, avoid, seeds)]

    def similarity(prompt: str, others: list[str]) -> float:
        with embed_lock:
            return similar.closest(prompt, others, embed)[1]

    def build_catalog(entry: dict) -> dict:
        return build.build_category(entry, rounds=1)

    return LiveGames(propose, build_catalog, similarity)
