"""AI-generated categories and answer lists, through ai-api-unified.

The model proposes categories and lists every valid answer it knows, with
aliases, the Wikipedia article for each answer, and a 1-5 salience guess.
It does not decide tiers: salience is one signal of three, and the scoring
step blends it with pageviews and word frequency.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ai_api_unified import AIFactory

log = logging.getLogger(__name__)

GENERATION_MODEL = "gpt-6-sol"

SYSTEM = """You build the answer catalog for a voice trivia game played in the United States and
Canada. Players hear a prompt such as "Name a cheese" and say one answer aloud. Any correct answer
counts, and the rarer it is, the more it scores. Your lists decide what counts as correct, so
correctness matters more than length: never include anything you are not sure is a true member."""

CATEGORY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["categories"],
    "properties": {
        "categories": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["seed", "prompt", "noun", "domain", "estimated_answers"],
                "properties": {
                    "seed": {"type": "string", "description": "The seed article this category grew from"},
                    "prompt": {"type": "string", "description": 'Spoken prompt, e.g. "Name a breed of dog"'},
                    "noun": {"type": "string", "description": 'Short Wikipedia disambiguation hint, e.g. "dog breed"'},
                    "domain": {"type": "string", "description": "Broad area, e.g. animals, food, geography, science"},
                    "estimated_answers": {"type": "integer", "description": "Rough count of valid answers"},
                },
            },
        }
    },
}

# Option B: the model writes bare names only, grouped by how often people say
# them. The group labels cost a few tokens each; per-answer fields (aliases,
# article titles, salience numbers) cost ~20 output tokens per answer, so the
# pipeline gets those from Wikipedia instead (titles by resolving the name,
# aliases from redirects). Output tokens are ~95% of a game's cost.
SALIENCE_GROUPS = {
    "very_common": 5,  # most people say it within seconds
    "common": 4,
    "known": 3,
    "uncommon": 2,
    "obscure": 1,  # only specialists know it
}
ANSWER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": list(SALIENCE_GROUPS),
    "properties": {g: {"type": "array", "items": {"type": "string"}} for g in SALIENCE_GROUPS},
}


@dataclass
class Category:
    seed: str
    prompt: str
    noun: str
    domain: str
    estimated_answers: int


def _client():
    return AIFactory.get_ai_completions_client(
        model_name=GENERATION_MODEL, completions_engine="openai", thinking="low"
    )


def _structured(prompt: str, schema: dict, max_tokens: int, *, cache: bool = True) -> dict:
    """One structured call. Identical requests are answered from ai-api-unified's
    response cache (see krillion/cache_store.py) unless cache=False."""
    result = _client().send_structured_output(
        prompt,
        response_schema=schema,
        system_prompt=SYSTEM,
        max_response_tokens=max_tokens,
        request_timeout_seconds=600.0,
        provider_options=None if cache else {"cache": "off"},
    )
    reason = str(getattr(result.finish_reason, "value", result.finish_reason))
    if reason != "complete" or result.data is None:
        raise RuntimeError(f"generation stopped early: {reason}")
    log.info("tokens in=%s out=%s cache_hit=%s", result.usage.input_tokens, result.usage.output_tokens,
             getattr(result, "cache_hit", False))
    return result.data


def propose_categories(count: int, existing: list[str], seeds: list[str]) -> list[Category]:
    """Seeds are random Wikipedia article titles. Models asked cold for
    categories return the same obvious ones every time; starting each one
    from a random seed is what makes them varied."""
    avoid = "\n".join(f"- {p}" for p in existing) or "(none yet)"
    seed_list = "\n".join(f"- {t}" for t in seeds)
    prompt = f"""Propose {count} new categories for the game, each grown from a different seed article below.

Start from the seed and climb to a group it belongs to that makes a good category. Examples:
- seed "Bowline" -> "Name a knot"
- seed "Cumulonimbus" -> "Name a type of cloud"
- seed "Tater tots" -> "Name a potato dish"
Skip seeds that lead nowhere playable (a person, a small village, a single sports season). Prefer
surprising categories over the obvious ones every quiz has; pick the most interesting seeds.

Seed articles:
{seed_list}

A good category:
- has membership that is factual and checkable: no opinions, no "best", no "favorite"
- has at least 80 valid answers, from household names to obscure but real ones
- is familiar in North America: a typical adult in the US or Canada knows what it is about.
  Skip categories rooted in another country's culture, sports or media (Bollywood films, cricket,
  Premier League clubs, Indian TV); global subjects (cheeses, clouds, knots) are fine
- is playable: a typical North American adult can name at least three answers without help, so
  no specialist jargon (financial ratios, algorithms, legal doctrines)
- has a listable set of members, roughly 80 to 2,000: not so broad that almost any title counts
  ("Name a debut album", "Name a song")
- has answers that are single named things, never pairs, relations or descriptions
  ("Name a border between two countries" fails)
- has answers that are short names a person can say aloud in 1 to 4 words, not numbers or sentences
- changes slowly: no current events, rankings, or people in the news
- is family friendly
- is phrased "Name a ..." or "Name an ..."

Spread them across different domains. Do not repeat or closely overlap these existing categories:
{avoid}"""
    # Never cached: every game must get new categories.
    data = _structured(prompt, CATEGORY_SCHEMA, 8_000, cache=False)
    return [Category(**c) for c in data["categories"]]


def generate_answers(category: Category, *, rounds: int = 2) -> list[dict]:
    """List valid answers as bare names, grouped by salience. A second round
    asks only for answers missing from the first, which improves recall on
    the obscure end. The prompt depends only on the category, so the response
    cache serves a repeat build of the same category for free."""
    answers: list[dict] = []
    rules = """- One canonical common English name per member, as a person would say it. No aliases, no
  descriptions, no parentheses.
- Each member once. Only true members: leave out anything you are unsure of, fictional items, and
  broad groupings that contain members.
- Group by how likely a typical North American adult is to say it when asked: very_common (most
  people say it within seconds), common, known, uncommon, obscure (only specialists know it)."""
    for i in range(rounds):
        if i == 0:
            prompt = f"""Prompt: "{category.prompt}" (Wikipedia hint: {category.noun})

List every valid answer you can, up to 300, from the most obvious to the most obscure.
{rules}"""
        else:
            listed = ", ".join(a["name"] for a in answers)
            prompt = f"""Prompt: "{category.prompt}" (Wikipedia hint: {category.noun})

These answers are already listed: {listed}

List further valid answers that are not in that list, especially obscure but real ones, up to 200.
Return empty groups if you cannot think of more you are sure of.
{rules}"""
        data = _structured(prompt, ANSWER_SCHEMA, 32_000)
        new = [{"name": n.strip(), "aliases": [], "wikipedia_title": None, "salience": SALIENCE_GROUPS[g]}
               for g in SALIENCE_GROUPS for n in data.get(g, []) if n and n.strip()]
        log.info("%s round %d: %d answers", category.prompt, i + 1, len(new))
        answers.extend(new)
        if not new:
            break
    return answers
