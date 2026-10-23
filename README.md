# Krillion

A voice trivia game where the obvious answer sinks. You hear a prompt such as
"Name a cheese" and say an answer out loud. Any correct answer counts, and the
rarer it is, the more it scores. Cheddar is Plankton. Cooleeney, a farmhouse
cheese from Tipperary, is One in a Krillion.

There is no question bank. AI generates every game's categories when you
start it, checks them against every category you've had before, and the game
scores the answers from data.

## Play it locally

Requires Python 3.11–3.13, [uv](https://docs.astral.sh/uv/), an OpenAI API
key, and optionally a Google Cloud service account for the recorded voices.

```bash
uv sync
cp .env.example .env                  # OPENAI_API_KEY, GOOGLE_APPLICATION_CREDENTIALS
cp models.example.json models.json    # model selections; set your Google Cloud project
uv run python server.py               # http://localhost:8000
```

Open the page in Chrome, Edge or Safari and click **New dive**. When the
questions are ready, press **Start**. Each question appears with 25 seconds of
air. Hold Space (or the **Hold to talk** button), say your answer, and let go.
Say "skip" to pass, or type in the answer box. To hear the questions read
aloud, turn on **Read questions aloud** in Settings (the gear, top right).

## The game

- **Every dive is new.** Each New dive gets seven freshly generated categories,
  and none repeats one you've had before. The dive waits on a ready screen
  until you press Start; Back keeps it for your next New dive. The server
  prepares the next game while you play the current one, so a new dive is
  usually ready at once.
- **Questions read aloud, if you want them.** Off by default: turn on **Read
  questions aloud** in Settings. Gemini TTS on Vertex AI then reads each
  question, directed as an upbeat game-show host, and "repeat" reads it again. Pick any of 30 Gemini voices
  and an American, British, Australian or Indian accent under **Settings**
  (the gear, top right), and press **Preview** to hear it. The server records each question in the
  chosen voice in about 4 seconds, in the background while you play. When a
  recording fails, the browser's own speech reads the question in the chosen
  accent. Results appear on screen with a chime; the game never speaks them.
- **Voice in, push to talk.** The mic hears you only while you hold Space or
  the **Hold to talk** button, so you can talk an answer over first. The
  browser's speech recognition streams what you say, and the server judges it
  (see [Judging answers](#judging-answers)). Chrome sends the audio to Google's
  speech service; Safari uses Apple's.
- **The dive.** A pink fish lives in the ocean behind the game and dives deeper
  with every scored answer, trailing bubbles, while the camera follows it down
  through five bands: kelp and light rays in the Shallows, coral and schools of
  fish at Schooler, jellyfish in the Thermocline, anglerfish in the Deep Cut,
  tube worms in the Trench. Rare answers set off sparkles, One in a Krillion a
  burst of diamonds, and a wrong answer gets a wobble and a "blub". With
  reduced motion turned on, the scene holds still and jumps to each new depth.
- **Rankings.** A column on the left keeps one list for the whole dive. Each
  question adds its section when it starts, the list scrolls up to the newest,
  and you can scroll back to any earlier one. Each section
  is a slice of that question's answer list, most common at the top: three
  answers from each tier plus the ones ranked just above and below yours. When
  your answer scores, the fish falls past the words, the answers below its
  spot slide down to open a gap, and it slides in carrying your answer at its
  exact rank ("#71 of 182"). An answer only the AI judge recognized goes in
  the middle of its tier, marked "new"; a skipped question shows its ladder
  with "No answer". On a screen under 1,200 px wide, the result shows the
  rank as text instead.
- **End a dive early.** End dive, next to Skip, takes two presses, then jumps
  to the summary of the questions played so far.
- **Air and speed.** The clock starts when the question appears, or after the
  game reads it aloud. A wrong
  answer costs 3 seconds, and a fast answer earns up to 50% more points.
- **Two modes.** Rare wins pays the tiers below; Popular wins reverses them, so
  the crowd's favorite pays 100.
- **Dive log.** A panel beside the game (below it on a phone) keeps every
  finished question with your answer and all its One in a Krillion answers (all
  the top answers in Popular mode). The end-of-dive summary lists every winning
  answer for every question. A list still building when its question ends fills
  in as soon as it's ready.

The page calls a small JSON API, served locally by `server.py`:

| Endpoint | Returns |
| --- | --- |
| `GET /api/dive?voice=Kore&accent=gb` | A new game: seven freshly generated questions |
| `POST /api/judge` `{"slug", "alts"}` | The matched answer, its tier and rank, and its ranking ladder, or `null` |
| `GET /api/ladder?slug=...&answer=...` | A question's ranking ladder after the fact (skipped questions, late lists) |
| `GET /api/reveal?slug=...` | Every One in a Krillion answer and every top answer, or `pending` |
| `GET /api/voices` | The voices and accents on offer |
| `GET /api/preview?voice=...&accent=...` | A short greeting in that voice |
| `GET /api/audio?slug=...&voice=...&accent=...` | The recorded question, recording it first if needed |

The answer lists stay on the server, so the answers never ship to the browser.

## How scoring works

Each question has a list of valid answers, and every answer sits in one tier:

| Tier | Points | Meaning |
| --- | --- | --- |
| Plankton | 10 | The answers almost everyone gives |
| Too Clever | 15 | Rare on paper, but what everyone says when trying to be clever |
| Schooler | 30 | Well known |
| Rare | 60 | Few people think of it |
| Deep Cut | 85 | Specialist knowledge |
| One in a Krillion | 100 | The least common verified answers |

Nobody writes these tiers by hand. The game builds them from data, and player
answers will refine them.

## How a game is generated

```
New dive ─► seeds ─► propose ─► dedupe ─► questions (game starts)
                                            │
                     in the background, per question:
                     answer list ─► verify ─► score ─► tier ─► data/live/catalog/
```

1. **Seed.** Sample 50 articles from Wikipedia's daily top-1,000 most-read
   lists for three random days in the past two years, which takes about a
   second. The surprise comes from the seeds. Without them, a model asked for
   categories returns the same dozen every time: dog breeds, cheeses, elements.
2. **Propose.** `gpt-6-sol` climbs from seeds to playable categories ("Bowline"
   → "Name a knot"). A category needs factual membership, roughly 80 to 2,000
   members, answers that are single named things, and at least three answers a
   typical adult can name unaided.
3. **Dedupe.** Embeddings (`text-embedding-3-small`) reject any proposal within
   cosine 0.84 of a category you've already had. "Name a breed of dog" and
   "Name a dog breed" score 0.94; "cheese" and "French cheese" score 0.74 and
   both stay. The history lives in `data/live/history.json`.
4. **Answer list.** `gpt-6-sol` lists every valid answer it knows as bare names,
   grouped from most common to obscure. The grouping is the model's salience
   guess; aliases and article titles come from Wikipedia in the next step.
5. **Verify.** Look up each name on Wikipedia, 50 per request: "Name (noun)",
   then "Name", then "Name noun", following redirects and rejecting
   disambiguation pages. The pipeline sets aside answers with no article, because
   that is where made-up answers turn up. The redirects pointing at each article become
   aliases, including common misspellings such as "Golden retreiver".
6. **Score.** Blend three signals, each turned into a percentile within its
   category first:
   - Wikipedia pageviews over the last 12 months (weight 0.40)
   - [wordfreq](https://github.com/rspeer/wordfreq) Zipf frequency (0.25, cut to
     0.08 for multi-word names)
   - the model's salience group (0.35)
7. **Tier.** Rank by the blended score: roughly the top 6% are Plankton, then
   Schooler to 35%, Rare to 70%, and Deep Cut after that. The least common 3% (at
   most five) become One in a Krillion. Too Clever stays empty: no text signal can
   tell "rare" from "rare but everyone says it", so only player answers can fill
   it.

An answer list takes about two minutes to build. Until it's ready, the AI judge
scores answers to that question.

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

## Cost and caching

All model calls go through
[ai-api-unified](https://pypi.org/project/ai-api-unified/). Output tokens are
most of the cost, so the answer-list step asks for bare names: grouping them by
salience costs a few tokens per group, where per-answer aliases, titles and
scores cost about 20 tokens per answer. For "Name a breed of dog" that cut one
generation pass from 7,675 output tokens to 1,969, and Wikipedia verified 264
of the 268 resulting answers.

Estimated cost of one seven-question game:

| Step | Model | Cost |
| --- | --- | --- |
| Propose categories | `gpt-6-sol`, 1 call | about $0.02 |
| Dedupe | `text-embedding-3-small` | under $0.0001 |
| Answer lists | `gpt-6-sol`, 7 calls of about 2,000 output tokens | about $0.14 |
| Judge unmatched answers | `gpt-6-luna`, thinking off | under $0.002 |
| Question audio | Gemini 2.5 Pro TTS, 7 short clips | about a cent (check Vertex billing) |
| **Total** | | **about $0.17** |

Speech recognition runs in the browser, and matching, wordfreq and Wikipedia
cost nothing.

ai-api-unified's response cache is on (`middleware` in `models.json`), backed
by a SQLite store in `data/cache/` so it survives restarts
(`krillion/cache_store.py`). The cache answers an identical request at no
cost: rebuilding a category's answer list, judging an answer someone has
already given, or embedding a category already checked. Entries expire after 30
days. Category proposals bypass the cache, since every game needs new ones.
The pipeline caches Wikimedia responses separately in `pipeline/.cache/`.

## Judging answers

`krillion/match.py` checks what the player said against the answer list. The
cheapest stage runs first, and each later stage runs only when the one before it
missed:

1. **Exact.** Normalize (case, accents, punctuation, filler such as "um, I'll
   say"), handle plurals, then look up the name and aliases.
2. **Typo.** [Damerau-Levenshtein](https://en.wikipedia.org/wiki/Damerau%E2%80%93Levenshtein_distance)
   distance, so a swapped pair ("gouad") counts as one edit (plain Levenshtein
   counts two). The allowance grows with length: none up to 4 letters (Mali and
   Bali must stay apart), 1 up to 8, 2 beyond that. Words most answers share
   ("cake" in a cake category) earn no allowance.
3. **Sound.** [Double Metaphone](https://en.wikipedia.org/wiki/Metaphone#Double_Metaphone)
   codes catch speech-recognition mishearings that edit distance cannot:
   "grew air" matches gruyère, "ketsal" matches quetzal.

The typo and sound stages never guess between two entries. A fuzzy hit counts
only when it is closer than the best hit for any other entry.

Anything still unmatched goes to the AI judge (`gpt-6-luna` with thinking off,
about 1–2 seconds), which also scores every answer while a question's list is
still building. It rates how common a valid answer is, and its best tier is
Deep Cut: One in a Krillion needs a verified list entry.

Embeddings stay out of matching. They measure relatedness: Gouda and Edam sit
close together, and merging them would wreck a game scored on rarity.

To check matching against a list from a game you've played:

```bash
uv run python -m pipeline.try_answers                     # list played categories
uv run python -m pipeline.try_answers name-a-wine-grape "pinot grigo" --tiers
```

## Repository layout

```
server.py         local dev server: the page plus the JSON API
public/           the voice game: index.html, styles.css, game.js, ocean.js (the dive scene)
krillion/
  live.py         generates each game, keeps the history, builds answer lists
  service.py      dive, judge and reveal, free of any web framework
  judge.py        AI judge for answers the list can't settle
  match.py        exact → typo → sound matcher
  ladder.py       the slice of the answer list an answer slides into
  normalize.py    text normalization; both sides must agree on it
  tiers.py        signal blending and tier assignment
  voices.py       the voices and accents players can choose
  tts.py          records questions with Gemini TTS, once per voice and accent
  cache_store.py  persistent store for ai-api-unified's response cache
pipeline/
  generate.py     AI categories and answer lists
  build.py        verify, score and tier one answer list
  wiki.py         Wikipedia lookups, redirects, pageviews, random seeds
  similar.py      embedding duplicate check
  http.py         cached HTTP client for Wikimedia
  try_answers.py  check answers against a list from the command line
tests/
```

Generated at play time and git-ignored: `data/live/` (categories asked and
their answer lists), `data/cache/` (response cache), `public/audio/` (recorded
questions). `.env`, `models.json` and service-account key files are git-ignored
too. Commit only the `.example` files.

Run the tests with `uv run pytest`.

## Status

Built:

- live generation: a new set of categories for every game, never repeating one
  already asked
- the voice game, with push to talk and 30 voices in four accents
- the answer matcher and the AI judge, with tests
- response caching with a persistent store

Known issues:

- **Category quality varies.** Most proposals play well; some are too broad or
  too specialist.
- **The AI judge scores the first question or two of a game**, since their
  answer lists are still building.
- **An article proves only that a thing exists.** "Blue cheese dressing" once
  passed as a cheese. A membership check with `gpt-6-luna` would catch it.

Next:

- **Free answer lists.** Fill answer lists from Wikidata and Wikipedia "List
  of" pages, and use the model only for the gaps.
- **Share categories between players.** Track what each player has seen, so a
  category built for one player serves everyone else for free.
- **API on Vercel**, on Postgres, recording every submitted answer.
- **Learning from players.** Shift each tier toward players' answer share as
  plays build up. This fills Too Clever and calibrates the signal weights.
