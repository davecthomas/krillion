"""Nearest list answers to what the player said, by embedding similarity.

Used only to build the AI judge's shortlist, never to decide a match:
embeddings measure relatedness, and Gouda sits as close to Edam as to
"gooda". The judge reads the shortlist and decides.

Each question's answer names are embedded once, in one batch call
(text-embedding-3-small, about $0.0002 for 600 names), and saved under
data/cache/embeddings/, so a restart costs nothing. Each lookup embeds the
heard text, which ai-api-unified's response cache answers for repeats.
Without an OpenAI key, or on any error, the shortlist just has no
embedding neighbors.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

CACHE = Path(__file__).resolve().parent.parent / "data" / "cache" / "embeddings"
_client = None
_lock = threading.Lock()
_loaded: dict[str, np.ndarray] = {}


def _get_client():
    global _client
    if _client is None:
        from ai_api_unified import AIFactory

        from .cache_store import install

        install()
        _client = AIFactory.get_ai_embedding_client(embedding_engine="openai")
    return _client


def _unit(rows: list[list[float]]) -> np.ndarray:
    m = np.asarray(rows, dtype=np.float32)
    return m / np.maximum(np.linalg.norm(m, axis=1, keepdims=True), 1e-9)


def _matrix(names: list[str]) -> np.ndarray:
    digest = hashlib.sha1("\n".join(names).encode()).hexdigest()[:16]
    with _lock:
        if digest in _loaded:
            return _loaded[digest]
        path = CACHE / f"{digest}.npy"
        if path.exists():
            m = np.load(path)
        else:
            out = _get_client().generate_embeddings_batch(names)
            m = _unit([r["embedding"] for r in out])
            CACHE.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f"{digest}.tmp.npy")
            np.save(tmp, m)
            tmp.replace(path)
        _loaded[digest] = m
        return m


def prepare(names: list[str]) -> None:
    """Embed a question's answer names ahead of the first lookup."""
    if names:
        _matrix(names)


def nearest(text: str, names: list[str], k: int = 8) -> list[int]:
    """Indexes into `names` of the k closest to `text`, best first."""
    if not text.strip() or not names:
        return []
    try:
        m = _matrix(names)
        q = _unit([_get_client().generate_embeddings(text)["embedding"]])[0]
    except Exception:
        log.warning("embedding neighbors unavailable", exc_info=True)
        return []
    scores = m @ q
    return [int(i) for i in np.argsort(-scores)[:k]]
