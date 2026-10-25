# Krillion

A voice trivia game where the obvious answer sinks. You hear a prompt such as
"Name a cheese" and say an answer out loud. Any correct answer counts, and the
rarer it is, the more it scores. Cheddar is Plankton. Cooleeney, a farmhouse
cheese from Tipperary, is One in a Krillion.

Questions come from a bank built ahead of time. A Claude Code skill writes
the categories and answer lists on your own Claude plan, and a deterministic
build step checks every answer against Wikipedia and Wikidata, then ranks
it with pageviews, word frequency, Google Books and Google Trends. Starting a
game makes no AI calls, and the game remembers which questions you've played,
so none repeats.

## Play it locally

Requires Python 3.11–3.13 and [uv](https://docs.astral.sh/uv/). An OpenAI API
key turns on the AI judge for valid answers missing from a list, and a Google
Cloud service account turns on the recorded voices. The game runs without
either.

```bash
uv sync
cp .env.example .env                  # OPENAI_API_KEY, GOOGLE_APPLICATION_CREDENTIALS
cp models.example.json models.json    # model selections; set your Google Cloud project
make serve                            # http://localhost:8765
```

The committed question package (`data/packages/default.jsonl.gz`) unpacks on
first start. Open the page in Chrome, Edge or Safari and click **New dive**,
then **Start**. Each question appears with 25 seconds of air. Hold Space (or
the **Hold to talk** button), say your answer, and let go. Say "skip" to pass,
or type in the answer box. To hear the questions read aloud, turn on **Read
questions aloud** in Settings (the gear, top right).

## The game

- **Every dive is new.** Each New dive draws seven questions you haven't
  played, from as many different domains as the bank allows, and records them
  in `data/live/asked.json`. No question repeats until you've played the whole
  bank; then the server asks you to build more. The dive waits on a ready
  screen until you press Start; Back keeps it for your next New dive.
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
- **The dive.** A krill lives in the ocean behind the game and dives deeper
  with every scored answer, trailing bubbles, while the camera follows it down
  through five bands: kelp and light rays in the Shallows, coral and schools of
  fish at Schooler, jellyfish in the Thermocline, anglerfish in the Deep Cut,
  tube worms in the Trench. Rare answers set off sparkles, One in a Krillion a
  burst of diamonds, and a wrong answer gets a wobble and a "blub". With
  reduced motion turned on, the scene holds still and jumps to each new depth.
- **Rankings.** A column on the left keeps one list for the whole dive. Each
  question adds its section when it starts, the list scrolls up to the newest,
  and you can scroll back to any earlier one. It stays beside the end-of-dive
  summary for review, and clears when the next dive starts. Each section
  is a slice of that question's answer list, most common at the top: three
  answers from each tier plus the ones ranked just above and below yours. When
  your answer scores, the krill falls past the words, the answers below its
  spot slide down to open a gap, and it slides in carrying your answer at its
  exact rank ("#71 of 182"). An answer only the AI judge recognized goes in
  the middle of its tier, marked "new"; a skipped question shows its ladder
  with "No answer". On a screen under 1,200 px wide, the result shows the
  rank as text instead.
- **Review, then move on.** After each question the game waits on a **Next question** button
  (or Enter), so you can scroll the rankings and see where your answer landed. The last
  question's button reads **See results**.
- **End a dive early.** End dive, next to Skip, takes two presses, then jumps
  to the summary of the questions played so far.
- **All-time high scores.** Each mode keeps a top 10 of the deepest dives,
  shown on the start screen and after every dive. A dive that makes the board
  asks for a name. The server keeps the boards in `data/live/highscores.json`
  and takes one score per game it started, never above what that game's
  questions can pay.
- **Air and speed.** The clock starts when the question appears, or after the
  game reads it aloud. A wrong
  answer costs 3 seconds, and a fast answer earns up to 50% more points. Under
  10 seconds a beep sounds each second; under 5 it rises in pitch and speeds
  up to about seven a second.
- **Two modes.** Rare wins pays the tiers below; Popular wins reverses them, so
  the crowd's favorite pays 100.
- **Dive log.** A panel beside the game (below it on a phone) keeps every
  finished question with your answer and all its One in a Krillion answers (all
  the top answers in Popular mode). The end-of-dive summary lists every winning
  answer for every question.

The page calls a small JSON API, served locally by `server.py`:

| Endpoint | Returns |
| --- | --- |
| `GET /api/dive?voice=Kore&accent=gb` | A new game: seven questions you haven't played |
| `POST /api/judge` `{"slug", "alts"}` | The matched answer, its tier and rank, and its ranking ladder, or `null` |
| `GET /api/ladder?slug=...&answer=...` | A question's ranking ladder after the fact (skipped questions) |
| `GET /api/reveal?slug=...` | Every One in a Krillion answer and every top answer |
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

## How the question bank is built

```
/krillion-catalog ─► data/catalog/raw/*.json        (written on your Claude plan)
make catalog      ─► data/catalog/questions/*.json  (verify, add, score, tier)
make package      ─► data/packages/default.jsonl.gz (committed; the game unpacks it)
```

`make questions` runs the last two steps together.

1. **Write.** The [`/krillion-catalog`](.claude/skills/krillion-catalog/SKILL.md)
   skill asks how many questions to write (default 500), reads what exists so
   it never repeats a prompt, and writes one file per question: the prompt,
   the noun Wikipedia uses to disambiguate members ("dog breed"), optionally
   the Wikipedia category and Wikidata class that list members, and 60–150
   answers grouped from very common to obscure. It runs in Claude Code on
   the plan of whoever runs it, so writing questions costs no API money. It
   writes in batches of 20 and resumes where it left off. The audience is
   North American: no categories rooted in another country's culture, such
   as cricket or Bollywood films. Global subjects such as cheeses stay.
2. **Verify.** Look up each name on Wikipedia, 50 per request: "Name (noun)",
   "Name (last word of noun)", "Name", "Name noun" ("Dorset sheep"), and for
   misses "Name (fruit)"-style titles and Title Case, following redirects and
   rejecting disambiguation pages. The first article whose short description
   is about the noun wins, because a bare name often means something else:
   "Cheddar" is a village, and "Goa" an Indian state rather than the board
   game. Failing that, the first article that isn't clearly something else:
   never a place, and outside music, film and history never a person or a
   work; outside animals, plants and food never a species ("Great White
   Shark" the Batman villain is not the fish). The build looks up towns as
   "Paris, Kentucky" and keeps them only when they are in that place. A writer can pin an article
   (`"Bow pose => Dhanurasana"`). The build sets aside answers with no
   article, because that is where made-up answers turn up. Characters on a
   shared "List of" page stay separate answers.
3. **Add (off by default).** `--extras` adds members from the Wikipedia
   category tree and Wikidata. Category trees stray into schools, dishes and
   paintings, and added members land in the top-scoring tier, so the default
   build uses only the writer's list.
4. **Aliases.** The redirects pointing at each article become aliases,
   including common misspellings such as "Golden retreiver".
5. **Score.** Blend six signals, each turned into a percentile within its
   question first. A signal missing for an answer drops out of its blend.

   | Signal | Weight | Source |
   | --- | --- | --- |
   | Wikipedia pageviews | 0.30 | 12 months (REST API) for questions built before; else the last 60 days, 50 articles a request |
   | Writer's salience group | 0.20 | the raw file |
   | Word frequency (Zipf) | 0.15, 0.05 for multi-word names | [wordfreq](https://github.com/rspeer/wordfreq) |
   | US search interest, five years | 0.15 | Google Trends, forty best-known answers |
   | Wikipedia language editions | 0.10 | Wikidata sitelinks |
   | American English book frequency, 2015–2019 | 0.10 | Google Books Ngram, 150 best-known answers |

   When the article needed more than the spoken name ("Mouse (knot)",
   "Newfoundland dog"), the name has another meaning, so word frequency,
   Ngram and Trends are left out for it. In a city question that holds only
   when the bare name leads to another article ("London" is London,
   England). The build asks Ngram and Trends only about the best-known
   answers, so it places their values in the top band of the list;
   otherwise Los Angeles would rank below Sacramento.
6. **Tier.** Rank by the blended score: roughly the top 6% are Plankton, then
   Schooler to 35%, Rare to 70%, and Deep Cut after that. The least common 3% (at
   most five) become One in a Krillion. Too Clever stays empty: no text signal can
   tell "rare" from "rare but everyone says it", so only player answers can fill
   it.
7. **Package.** Every built question goes into one gzipped JSON Lines file,
   one question per line, sorted by slug so unchanged questions produce the
   same bytes. A manifest beside it lists the count, domains and slugs. The
   format loads straight into a database: one row per line, keyed by slug.

The build spaces out its requests per site, shared by every job (`make
catalog JOBS=5`), and a 429 pauses all of them: Wikipedia blocks an address
for minutes when bursts overrun it. 500 questions take about two hours with
five jobs; keep the computer awake (`caffeinate -i make catalog JOBS=5` on a
Mac). It caches every response in `pipeline/.cache/`, so a rebuild after a
lookup change is fast, and `python -m pipeline.catalog --retier` re-scores
built questions from saved signals with no network at all. Google Trends
and Books Ngram have no official API: a failure there means a missing signal,
never a failed build. Trends rate-limits after a few dozen requests, so after
two failures in a row the build skips it for the rest of that question.
`--no-trends` skips Trends.

To publish questions you wrote, commit the raw files and the package. A
local build always wins over a packaged one, so a question you rebuilt is
never overwritten when the package unpacks.

### Why several signals

Before building, we tested two signals against hand-written tiers for 8
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
- **Search interest counts need.** Chihuahua outscores Labrador Retriever on
  Google Trends, partly because people search for a breed while choosing one.

Blending the signals spreads those errors out. Player data is the ground truth
that will replace the weights.

## Cost and caching

| Step | What runs | Cost |
| --- | --- | --- |
| Write questions | Claude Code, `/krillion-catalog` | your Claude plan's usage, about 2,000 output tokens a question |
| Build and package | Wikipedia, Wikidata, Google Trends and Ngram, wordfreq | free |
| Start a game | reads the bank | free |
| Judge an answer missing from the list | `gpt-6-luna`, thinking off, plus one embedding | under $0.002 a game |
| Question audio, when turned on | Gemini 2.5 Pro TTS, 7 short clips | about a cent a game (check Vertex billing) |

Speech recognition runs in the browser, and matching costs nothing.

The judge's calls go through [ai-api-unified](https://pypi.org/project/ai-api-unified/)
with its response cache on (`middleware` in `models.json`), backed by a SQLite
store in `data/cache/` (`krillion/cache_store.py`), so judging an answer
someone has already given costs nothing. Entries expire after 30 days.

## Judging answers

`krillion/match.py` checks what the player said against the answer list.
Speech recognition sends up to five guesses, best first. The best guess goes
through every stage below; the others may only match a name exactly, as a
whole phrase, so a weak guess ("porties", a nickname for the Portuguese Water
Dog) never beats a clear one ("Pyrenees"). The cheapest stage runs first:

1. **Exact.** Normalize (case, accents, punctuation, filler such as "um, I'll
   say"), handle plurals, then look up the name and aliases.
2. **Partial.** The heard words appear in exactly one answer's name:
   "Pyrenees" is Great Pyrenees.
3. **Typo.** [Damerau-Levenshtein](https://en.wikipedia.org/wiki/Damerau%E2%80%93Levenshtein_distance)
   distance, so a swapped pair ("gouad") counts as one edit (plain Levenshtein
   counts two). The allowance grows with length: none up to 4 letters (Mali and
   Bali must stay apart), 1 up to 8, 2 beyond that. Words most answers share
   ("cake" in a cake category) earn no allowance.
4. **Sound.** [Double Metaphone](https://en.wikipedia.org/wiki/Metaphone#Double_Metaphone)
   codes catch speech-recognition mishearings that edit distance cannot:
   "grew air" matches gruyère, "ketsal" matches quetzal.
5. **Other guesses.** Exact whole-phrase matches only.

The partial, typo and sound stages never guess between two entries. When the
heard words sit in several names ("water dog"), the matcher skips the fuzzy
stages and leaves the choice to the judge.

Anything still unmatched goes to the AI judge (`gpt-6-luna` with thinking off,
about 1–2 seconds) with a shortlist of up to eight list answers: those whose
names hold the heard words, then the nearest by embedding
(`text-embedding-3-small`, `krillion/neighbors.py`). When the judge names a
list answer, the answer scores at that entry's rank and tier: "pyrenese" is
Great Pyrenees, #38 of 616. Otherwise it rates how common a valid answer is for
a North American adult, and its best tier is Deep Cut: One in a Krillion needs
a verified list entry. Without an OpenAI key, an answer missing from the list
is a miss.

Embeddings only build the shortlist; the judge decides. They measure
relatedness: Gouda and Edam sit close together, and treating closeness as a
match would wreck a game scored on rarity. Each question's answer names are
embedded once, in one batch call (about $0.0002), when a dive starts, and kept
in `data/cache/embeddings/`.

To check matching against a built question:

```bash
uv run python -m pipeline.try_answers                     # list built questions
uv run python -m pipeline.try_answers name-a-knot "bowlin" --tiers
```

## Repository layout

```
Makefile          catalog, package, questions, serve, test
server.py         local dev server: the page plus the JSON API
public/           the voice game: index.html, styles.css, game.js, ocean.js (the dive scene)
.claude/skills/krillion-catalog/
                  the skill that writes raw questions on your Claude plan
krillion/
  bank.py         the question bank and the asked-list
  scores.py       all-time high scores, a top 10 per mode
  service.py      dive, judge and reveal, free of any web framework
  judge.py        AI judge for answers the list can't settle
  neighbors.py    embedding shortlist for the judge
  match.py        exact → typo → sound matcher
  ladder.py       the slice of the answer list an answer slides into
  normalize.py    text normalization; both sides must agree on it
  tiers.py        signal blending and tier assignment
  voices.py       the voices and accents players can choose
  tts.py          records questions with Gemini TTS, once per voice and accent
  cache_store.py  persistent store for ai-api-unified's response cache
pipeline/
  catalog.py      build raw questions: verify, add members, score, tier
  package.py      bundle built questions into a package, and unpack one
  wiki.py         Wikipedia lookups, descriptions, redirects, pageviews
  wikidata.py     Wikidata class members and sitelink counts
  categories.py   Wikipedia category tree members
  signals.py      Google Books Ngram and Google Trends
  http.py         cached, per-host throttled HTTP client
  try_answers.py  check answers against a built question
data/
  catalog/raw/    raw questions from the skill (committed)
  packages/       built question packages (committed)
tests/
```

Local and git-ignored: `data/catalog/questions/` (built questions),
`data/live/` (which questions this machine has asked), `data/cache/` (response
cache), `public/audio/` (recorded questions). `.env`, `models.json` and
service-account key files are git-ignored too. Commit only the `.example`
files.

Run the tests with `make test`.

## Status

Built:

- a question bank written on a Claude plan and built from open data, with an
  asked-list so no question repeats
- the voice game, with push to talk and 30 voices in four accents
- the answer matcher and the AI judge, with tests

Known issues:

- **Fallback articles can still be wrong.** When no article names the
  topic, the build takes the first that isn't clearly something else. A
  few answers borrow another meaning's pageviews that way; fix one by
  rewording it or pinning its article.
- **60-day pageviews are seasonal.** Yom Kippur ranks high among holidays
  when it falls inside the window.
- **An article proves only that a thing exists.** "Blue cheese dressing" once
  passed as a cheese.

Next:

- **Vercel + Postgres.** Import the package into Postgres and keep the
  asked-list per player.
- **Learn from players.** Replace the signal weights with how often players
  give each answer, which also fills Too Clever.
