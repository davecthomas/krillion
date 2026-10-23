"""AI judge for answers the catalog can't settle.

It handles answers that arrive before a live category's catalog is built, and
valid answers the catalog lacks. It uses a fast model with thinking off
(about 1-2 seconds), and a timeout: a slow judge counts as no answer, never
as a frozen game.
"""

from __future__ import annotations

import logging

from .tiers import DEEP_CUT, PLANKTON, RARE, SCHOOLER

JUDGE_MODEL = "gpt-6-luna"
TIMEOUT_S = 6.0
log = logging.getLogger(__name__)

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["valid", "name", "salience"],
    "properties": {
        "valid": {"type": "boolean"},
        "name": {"type": ["string", "null"], "description": "Canonical name of the answer, or null"},
        "salience": {"type": "integer", "description": "5 = most people say it; 1 = only specialists know it"},
    },
}

# Without catalog data, salience alone sets the tier. One in a Krillion needs
# a verified catalog entry, so the judge tops out at Deep Cut.
SALIENCE_TIER = {5: PLANKTON, 4: SCHOOLER, 3: RARE, 2: DEEP_CUT, 1: DEEP_CUT}

_client = None


def _get_client():
    global _client
    if _client is None:
        from ai_api_unified import AIFactory

        from .cache_store import install

        install()  # a repeated answer is judged from the persistent response cache

        _client = AIFactory.get_ai_completions_client(
            model_name=JUDGE_MODEL, completions_engine="openai", thinking="off")
    return _client


def judge(prompt: str, alts: list[str]) -> dict | None:
    """{"name", "tier"} for a correct answer, else None."""
    heard = " / ".join(f'"{a}"' for a in alts[:3])
    try:
        r = _get_client().send_structured_output(
            f'Trivia prompt: "{prompt}".\n'
            f"The player said (speech-to-text alternatives, best first; may be misheard): {heard}\n"
            "Is it a real, correct answer to the prompt? Be strict about correctness and generous about "
            "speech-recognition spelling. If it is, give its canonical name and how likely a typical "
            "North American adult is to say it (salience 1-5).",
            response_schema=SCHEMA, max_response_tokens=300, request_timeout_seconds=TIMEOUT_S)
    except Exception:
        log.warning("judge failed for %r", alts[:1], exc_info=True)
        return None
    d = r.data or {}
    if not d.get("valid") or not d.get("name"):
        return None
    return {"name": d["name"], "tier": SALIENCE_TIER.get(int(d.get("salience") or 3), RARE)}
