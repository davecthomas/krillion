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

SYSTEM = """You build the answer catalog for a voice trivia game.
Players hear a prompt such as "Name a cheese" and say one answer aloud. Any correct answer
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

ANSWER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answers"],
    "properties": {
        "answers": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "aliases", "wikipedia_title", "salience"],
                "properties": {
                    "name": {"type": "string", "description": "Common English name, as a person would say it"},
                    "aliases": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Other names and spellings for the same thing",
                    },
                    "wikipedia_title": {
                        "type": ["string", "null"],
                        "description": "Exact title of the English Wikipedia article about this specific item, or null",
                    },
                    "salience": {
                        "type": "integer",
                        "description": "5 = most people say it within seconds; 1 = only specialists know it",
                    },
                },
            },
        }
    },
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


def _structured(prompt: str, schema: dict, max_tokens: int) -> dict:
    result = _client().send_structured_output(
        prompt,
        response_schema=schema,
        system_prompt=SYSTEM,
        max_response_tokens=max_tokens,
        request_timeout_seconds=600.0,
    )
    reason = str(getattr(result.finish_reason, "value", result.finish_reason))
    if reason != "complete" or result.data is None:
        raise RuntimeError(f"generation stopped early: {reason}")
    log.info("tokens in=%s out=%s", result.usage.input_tokens, result.usage.output_tokens)
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
- seed a minor cricket ground -> "Name a cricket fielding position"
Skip seeds that lead nowhere playable (a person, a small village, a single sports season). Prefer
surprising categories over the obvious ones every quiz has; pick the most interesting seeds.

Seed articles:
{seed_list}

A good category:
- has membership that is factual and checkable: no opinions, no "best", no "favorite"
- has at least 80 valid answers, from household names to obscure but real ones
- is playable: a typical adult can name at least three answers without help
- has answers that are short names a person can say aloud in 1 to 4 words, not numbers or sentences
- changes slowly: no current events, rankings, or people in the news
- is family friendly
- is phrased "Name a ..." or "Name an ..."

Spread them across different domains. Do not repeat or closely overlap these existing categories:
{avoid}"""
    data = _structured(prompt, CATEGORY_SCHEMA, 8_000)
    return [Category(**c) for c in data["categories"]]


def generate_answers(category: Category, *, rounds: int = 2) -> list[dict]:
    """List valid answers. A second round asks only for answers missing from
    the first, which improves recall on the obscure end."""
    answers: list[dict] = []
    for i in range(rounds):
        if i == 0:
            prompt = f"""Prompt: "{category.prompt}" (Wikipedia hint: {category.noun})

List every valid answer you can, up to 300, from the most obvious to the most obscure.
- Each answer is one distinct member. Put alternative names and spellings in aliases, never as separate answers.
- Only true members. Leave out anything you are unsure of, fictional items, and broad groupings that contain members.
- wikipedia_title is the exact English Wikipedia title for that specific item, such as "Date palm" or
  "Pointer (dog breed)". Use null if you are not confident an article exists.
- salience: how likely a typical adult is to say it when asked, 5 (most say it) to 1 (only specialists)."""
        else:
            listed = ", ".join(a["name"] for a in answers)
            prompt = f"""Prompt: "{category.prompt}" (Wikipedia hint: {category.noun})

These answers are already listed: {listed}

List further valid answers that are not in that list or its aliases, especially obscure but real ones,
up to 200. Same rules: true members only, aliases instead of duplicates, exact Wikipedia title or null,
salience 1 to 5. Return an empty list if you cannot think of more you are sure of."""
        data = _structured(prompt, ANSWER_SCHEMA, 64_000)
        new = data["answers"]
        log.info("%s round %d: %d answers", category.prompt, i + 1, len(new))
        answers.extend(new)
        if not new:
            break
    return answers
