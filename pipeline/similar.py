"""Reject category proposals that duplicate an existing category.

Rewordings of one category ("Name a dog breed" / "Name a breed of dog") score
about 0.94 cosine with text-embedding-3-small; "dinosaur" vs "dinosaur genus"
0.85. Related but distinct categories ("cheese" / "French cheese",
"language" / "programming language") land between 0.70 and 0.80.
"""

from __future__ import annotations

import math

from ai_api_unified import AIFactory

DUPLICATE_AT = 0.84


class Embeddings:
    """Unit-length embeddings by text. Repeats come from ai-api-unified's
    response cache (persistent, see krillion/cache_store.py); the dict here
    only saves re-normalizing within one process."""

    def __init__(self) -> None:
        self._client = None
        self._seen: dict[str, list[float]] = {}

    def __call__(self, text: str) -> list[float]:
        if text not in self._seen:
            if self._client is None:
                self._client = AIFactory.get_ai_embedding_client(embedding_engine="openai")
            v = self._client.generate_embeddings(text)["embedding"]
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            self._seen[text] = [x / n for x in v]
        return self._seen[text]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))  # vectors are stored unit-length


def closest(text: str, others: list[str], embed: Embeddings) -> tuple[str | None, float]:
    v = embed(text)
    best, score = None, -1.0
    for o in others:
        s = cosine(v, embed(o))
        if s > score:
            best, score = o, s
    return best, score
