---
name: krillion-catalog
description: Writes new questions and answer lists for the Krillion voice trivia game into data/catalog/raw/, on your own plan's tokens instead of a paid API. Asks how many (default 500), works in batches, resumes where it left off, then builds and packages them with `make questions`.
---

# Krillion catalog writer

You write questions for a voice trivia game. Players hear "Name a cheese",
say one answer, and the rarer their correct answer, the more it scores. You
write the prompt and the answers; a deterministic build step verifies every
answer on Wikipedia, adds members from Wikipedia categories and Wikidata,
and ranks them with pageviews, word frequency, Google Books and Google
Trends. Nothing you write is trusted as-is, but a wrong answer wastes a
verification lookup and a wrong prompt wastes a whole question.

## Steps

1. **Ask how many questions to write.** Default 500. A question costs about
   2,000 output tokens, so 500 is a long run: write in batches of 20 files
   and keep going until the count is reached. If the session ends early, the
   next run resumes, because step 2 counts what exists.
2. **Read what exists.** List `data/catalog/raw/*.json` and read every
   `prompt` (a `grep '"prompt"' data/catalog/raw/*.json` is enough). Never
   write a prompt that is already there or a close rewording of one
   ("Name a dog breed" when "Name a breed of dog" exists).
3. **Choose categories.** Spread them across domains: food and drink,
   animals, plants, geography, science, sports, music, film and TV, books,
   history, art and architecture, household, vehicles, games and toys,
   fashion, language, business and brands, technology, mythology and
   religion, and everyday life. Vary difficulty and surprise: "Name a knot"
   and "Name a cloud type" are better than the categories every quiz has.
4. **Write one file per question**, `data/catalog/raw/<slug>.json`, where
   the slug is the prompt lower-cased with non-letters replaced by hyphens
   ("Name a breed of dog" → `name-a-breed-of-dog.json`). Use the format
   below.
5. **Build and package**: run `make questions`. It builds only the new raw
   files (a few minutes each: Wikipedia, Wikidata and Google Trends are
   throttled), then rewrites `data/packages/default.jsonl.gz` and its
   manifest. Report how many questions were written, the build's answer
   counts, and remind the user that the raw files and the package are the
   files to commit.

## A good question

- Phrased "Name a ..." or "Name an ...", spoken aloud.
- Familiar to adults in the United States and Canada. No categories rooted
  in another country's culture, sport or media (cricket, Bollywood, Premier
  League clubs). Global subjects (cheeses, clouds, knots) are fine.
- Factual, checkable membership: no "best", "favorite", or opinions.
- 80 to 2,000 valid members in the world, each with a Wikipedia article.
- A typical adult can name at least three without help, so no specialist
  jargon (financial ratios, algorithms, legal doctrines).
- Answers are single named things said in one to four words: not pairs,
  relations, numbers, descriptions or sentences.
- Changes slowly: no current events, rankings or people in the news.
- Family friendly.

## The answer list

List the valid members you are sure of, 60 to 150 names, from the most
obvious to the most obscure, grouped by how likely a typical North American
adult is to say it when asked. Stop when you run out of members you are sure
of: the build step adds the obscure rest from Wikipedia and Wikidata, and a
long list padded with variants, expansions, dishes or made-up combinations
("Pasta alla Campana", "Yahtzee Travel") is worse than a short true one.

- `very_common`: most people say it within seconds
- `common`
- `known`
- `uncommon`
- `obscure`: only specialists know it

Rules: one canonical English name per member, as a person would say it, no
aliases or parentheses; each member once; only true members, leaving out
anything you are unsure of, fictional items, expansions and editions of a
member already listed, and broad groupings that contain members. Obscure but
real answers are valuable: they become the top-scoring tier once Wikipedia
confirms them.

## File format

```json
{
  "prompt": "Name a breed of dog",
  "noun": "dog breed",
  "domain": "animals",
  "wikipedia_category": "Category:Dog breeds",
  "wikidata_class": "Q39367",
  "answers": {
    "very_common": ["Labrador Retriever", "German Shepherd", "Golden Retriever"],
    "common": ["Beagle", "Dachshund"],
    "known": ["Basenji"],
    "uncommon": ["Otterhound"],
    "obscure": ["Mudi"]
  }
}
```

- `noun`: the Wikipedia disambiguator for a member, used to look up
  "Pointer (dog breed)". Singular.
- `wikipedia_category`: the English Wikipedia category that lists members,
  when you are confident it exists. Leave it out otherwise; a wrong category
  adds junk answers.
- `wikidata_class`: the Wikidata item for the member class, when you know it.
  Leave it out otherwise.
- Leave both out when your list is already complete (the 88 constellations,
  the 50 states): added members can only be noise there.
