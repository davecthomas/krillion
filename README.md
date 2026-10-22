# Krillion

A voice trivia game where the obvious answer sinks. You hear a prompt such as
"Name a cheese" and say an answer out loud. Any correct answer counts, and the
rarer it is, the more it scores. Cheddar is Plankton. Cooleeney, a farmhouse
cheese from Tipperary, is One in a Krillion.

This repository holds the playable game, the pipeline that builds its answer
catalogs, and the matcher that judges spoken answers.

## Play it locally

```bash
uv sync
uv run python server.py        # http://localhost:8000
```

Open the page in Chrome, Edge or Safari, click **Practice dive**, and allow the
microphone. The game reads each question aloud, and you have 25 seconds of air
to say an answer. Say "repeat" to hear the question again or "skip" to pass, or
type in the answer box. Playing needs no API keys: the repository includes the
catalogs and recorded questions.

## The game

- **Voice out, for the question only.** The pipeline records each category's
  question once with Gemini TTS on Vertex AI (voice "Puck", directed as an upbeat
  game-show host) and stores it in `public/audio/`. When a recording is missing,
  the browser's own speech reads the question instead. Results appear on
  screen with a chime; the game never speaks them.
- **Voice in, for answers.** The browser's speech recognition streams what the
  player says, and the server judges each phrase (see
  [Matching spoken answers](#matching-spoken-answers)). Chrome sends the audio
  to Google's speech service; Safari uses Apple's.
- **Air and speed.** The clock starts after the game reads the question. A wrong
  answer costs 3 seconds, and a fast answer earns up to 50% more points.
- **Two modes.** Rare wins pays the tiers below; Popular wins reverses them, so
  the crowd's favorite pays 100.
- **Daily and practice dives.** A daily dive uses the date as its random seed,
  so everyone gets the same questions that day. A practice dive draws at random
  and skips the categories you played recently. Scores stay in the browser.
- **Every krillion answer.** After each question, click the revealed answer to
  list all the One in a Krillion answers (or all the top answers in Popular
  mode).

The page calls a small JSON API, served locally by `server.py`:

| Endpoint | Returns |
| --- | --- |
| `GET /api/dive?mode=daily&date=2026-10-22` | Up to seven questions, with their audio paths |
| `GET /api/dive?mode=practice&recent=slug,slug` | The same, skipping recently played categories |
| `POST /api/judge` `{"slug", "alts"}` | The matched answer and its tier, or `null` |
| `GET /api/reveal?slug=...` | Every One in a Krillion answer and every top answer |

The catalogs stay on the server, so the answers never ship to the browser.

## How scoring works

Each prompt has a catalog of valid answers, and every answer sits in one tier:

| Tier | Points | Meaning |
| --- | --- | --- |
| Plankton | 10 | The answers almost everyone gives |
| Too Clever | 15 | Rare on paper, but what everyone says when trying to be clever |
| Schooler | 30 | Well known |
| Rare | 60 | Few people think of it |
| Deep Cut | 85 | Specialist knowledge |
| One in a Krillion | 100 | The least common verified answers |

Nobody writes these tiers by hand. A pipeline builds them from data, and player
answers will refine them.

## The catalog pipeline

```
seed articles ─► propose ─► generate ─► verify ─► score ─► tier ─► data/catalog/*.json
  (Wikipedia)    (AI)       (AI)        (Wikipedia) (3 signals)
```

1. **Seed.** Draw 200 random Wikipedia articles and keep the 40 with the most
   pageviews. The surprise comes from the seeds. Without them, a model asked for
   categories returns the same dozen every time: dog breeds, cheeses, elements.
2. **Propose.** The model climbs from a seed to a playable category ("Bowline" →
   "Name a knot"). It must have at least 80 answers, factual membership, and at
   least three answers a typical adult can name unaided. Embeddings reject any
   proposal that duplicates an existing category (cosine 0.84 or above).
   Proposals land in `data/categories.json` for review before any build.
3. **Generate.** The model lists every valid answer it knows, in two passes. The
   second pass asks only for answers missing from the first. Each answer comes
   with aliases, its Wikipedia article title, and a 1–5 guess at how often people
   say it.
4. **Verify.** Look up the titles on Wikipedia, 50 per request, following
   redirects and rejecting disambiguation pages. The pipeline sets aside answers with no
   article, because that is where made-up answers turn up ("Giant Alaskan
   Malamute"). Two answers that land on one article merge into one. The redirects
   pointing at each article become extra aliases, including common misspellings
   such as "Golden retreiver".
5. **Score.** Blend three signals, each turned into a percentile within its
   category first:
   - Wikipedia pageviews over the last 12 months (weight 0.40)
   - [wordfreq](https://github.com/rspeer/wordfreq) Zipf frequency (0.25, cut to
     0.08 for multi-word names)
   - the model's salience guess (0.35)
6. **Tier.** Rank by the blended score: roughly the top 6% are Plankton, then
   Schooler to 35%, Rare to 70%, and Deep Cut after that. The least common 3% (at
   most five) become One in a Krillion. Too Clever stays empty: no text signal can
   tell "rare" from "rare but everyone says it", so only player answers can fill
   it.
7. **Record.** `pipeline.voice` records each new question with Gemini TTS.

### Why three signals

Before building, we tested each signal against hand-written tiers for 8
categories. Spearman rank correlation, where −1 is perfect agreement:

| Signal | Dog breeds | Birds | Fruit |
| --- | --- | --- | --- |
| Word frequency | −0.58 | −0.80 | −0.67 |
| Wikipedia pageviews | −0.69 | −0.65 | −0.62 |

Each signal fails in its own way:

- **Word frequency counts the word across all its meanings.** "Date" and
  "pointer" look common because of their other meanings. wordfreq scores a
  phrase from its separate words, so "wife carrying" looks common too.
- **Pageviews count curiosity.** Secretarybird draws 465k views a year because
  it is fun to read about, yet few people would name it first.

Blending the signals spreads those errors out. Player data is the ground truth
that will replace the weights.

### Running it

Requires Python 3.11–3.13 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env                  # OPENAI_API_KEY, GOOGLE_APPLICATION_CREDENTIALS
cp models.example.json models.json    # model selections; set your Google Cloud project

uv run python -m pipeline.build propose --count 12   # new categories into data/categories.json
# review data/categories.json; set "enabled": false on any you don't want
uv run python -m pipeline.build build --limit 5      # build catalogs not built yet
uv run python -m pipeline.build build --only name-a-cheese --force
uv run python -m pipeline.voice                      # record questions that have no audio yet
uv run python -m pipeline.try_answers name-a-cheese "grew air" "gouad"
```

`try_answers` judges answers the way the game will, and shows the match, the
method, the tier and the points. Add `--tiers` to see a sample of each tier.

`.env`, `models.json` and service-account key files are git-ignored. Commit
only the `.example` files. `GOOGLE_APPLICATION_CREDENTIALS` points at a Google
Cloud service-account key with the Text-to-Speech API enabled.

All model calls go through
[ai-api-unified](https://pypi.org/project/ai-api-unified/): `gpt-6-sol` for
generation, `text-embedding-3-small` for the duplicate check, and
`gemini-2.5-pro-tts` on Vertex AI for the recorded questions. One category
costs about $0.12 in model usage and takes about 3½ minutes. Most of that time is
the pause between Wikipedia requests, which Wikimedia's rate limits require.
The pipeline caches Wikimedia responses in `pipeline/.cache/`, so a rebuild only
repeats the model calls.

## Matching spoken answers

`krillion/match.py` judges what the player said. The cheapest stage runs first,
and each later stage runs only when the one before it missed:

1. **Exact.** Normalize (case, accents, punctuation, filler such as "um, I'll
   say"), handle plurals, then look up the name and aliases.
2. **Typo.** [Damerau-Levenshtein](https://en.wikipedia.org/wiki/Damerau%E2%80%93Levenshtein_distance)
   distance, so a swapped pair ("gouad") counts as one edit (plain Levenshtein counts two). The
   allowance grows with length: none up to 4 letters (Mali and Bali must stay
   apart), 1 up to 8, 2 beyond that.
3. **Sound.** [Double Metaphone](https://en.wikipedia.org/wiki/Metaphone#Double_Metaphone)
   codes catch speech-recognition mishearings that edit distance cannot:
   "grew air" matches gruyère, "ketsal" matches quetzal.

The typo and sound stages never guess between two entries. A fuzzy hit counts
only when it is closer than the best hit for any other entry. Whatever is still
unmatched goes to an AI judge, which can also accept a valid answer the catalog
lacks.

Embeddings stay out of matching. They measure relatedness: Gouda and Edam sit
close together, and merging them would wreck a game scored on rarity.

## Repository layout

```
server.py       local dev server: the page plus the JSON API
public/
  index.html, styles.css, game.js   the voice game
  audio/        one recorded question per category
krillion/       shared by the pipeline and the API
  normalize.py  text normalization; both sides must agree on it
  match.py      exact → typo → sound matcher
  tiers.py      signal blending and tier assignment
  service.py    dive, judge and reveal, free of any web framework
pipeline/
  build.py      command-line entry point
  generate.py   AI categories and answer lists (ai-api-unified)
  wiki.py       Wikipedia verification, redirects, pageviews, random seeds
  similar.py    embedding duplicate check
  voice.py      records each question with Gemini TTS
  try_answers.py  judge answers against a catalog from the command line
  http.py       cached, rate-limited HTTP client for Wikimedia
data/
  categories.json   proposed categories, reviewed by hand
  catalog/          one built catalog per category
tests/
```

Run the tests with `uv run pytest`.

## Status

Built:

- the voice game, playable locally, with recorded questions
- the catalog pipeline and five catalogs: dog breeds, car brands, game shows,
  cheeses and cakes
- the answer matcher, with tests

Known issues:

- **The Wikipedia check is too strict.** It sets aside real answers that have
  no article of their own: cakes lost 187 of 426 answers, including "coffee
  cake".
- **It also proves too little.** An article proves only that the thing exists:
  "Blue cheese dressing" passed as a cheese. A second check with `gpt-6-luna` on every answer would fix both, for about $0.01 per category.
- **No AI judge yet.** A valid answer missing from the catalog counts as wrong.

Next:

- **API on Vercel.** Move `krillion/service.py` behind Vercel functions, on
  Postgres. The API records every submitted answer.
- **Learning from players.** Each tier starts from the data estimate and shifts
  toward players' answer share as plays build up. This fills Too Clever and
  calibrates the signal weights.
- **More questions per category.** Tag answers with Wikidata facts (country,
  era) so one catalog can also serve "Name a dog breed from Japan".
