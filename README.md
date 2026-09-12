# sentence-recommender

Builds an ordered **i+1 roadmap** — a sequence of learning units where each
step's example sentence contains exactly one thing you don't yet know — and
reviews it with spaced repetition.

## What a "unit" is

Two kinds, treated identically by the roadmap:

| kind | example | source |
|---|---|---|
| `lemma` | `merken` | spaCy lemmatisation |
| `pattern` | `jdm. (Dat) etw. (Akk) merken` | the sentence-to-phrase matcher |

A sentence is i+1 when exactly one of its units is unknown — whichever kind.
Knowing the word *merken* is separate from knowing that it takes dative +
accusative, so both are scheduled.

## Sources

- **Tatoeba** — 276k human-written German sentences with English translations.
  The primary corpus.
- **Subtitles** — the `language-app` Postgres corpus. Subtitle rows are not
  sentences: a third do not end in punctuation and many are cut mid-clause.
  `MergeCorrector` rejoins and re-splits them; `--corrector llm` instead sends
  each stretch of lines to the local model, which also fixes punctuation and
  transcription errors. Any chunk the model fails on falls back to the
  rule-based corrector, so nothing is lost to a bad reply.
- **Machine captions** — the same treatment, over videos that have no
  hand-written track at all. Where one exists it is always preferred: measured
  over thirty videos holding both, the machine track gave 31% fewer teachable
  sentences. Where none exists the comparison is against nothing, so
  `add-channel --auto` takes a machine track that passes three tests — it
  punctuates, it is actually German, and it is long enough. These land in
  their own build, `subtitle:auto`, and never beside the hand-written ones;
  the **Studying** switch on every page is the filter, and the videos are
  marked `auto` wherever they are named. `ingest/auto_captions.py` is the
  gate, and TODO item 7 is why each test is there.
- **Generated** — a local model fills gaps where no natural i+1 sentence
  exists for a unit. Every generated sentence is re-analysed and kept only if
  its unknowns are exactly the target.

## Commands

Run everything through the project's interpreter, `.venv/bin/python` — the
bare `python` on your PATH is a different environment and will not have
`spacy-lookups-data`, which changes how spaCy lemmatises German. `python`
below means `.venv/bin/python`.

```
python main.py serve                      browse the results at localhost:8765
python main.py add-video <ID_OR_URL>      scrape a YouTube video into the catalogue
python main.py add-channel <ID|@HANDLE>   scrape a whole channel
python main.py add-channel <CH> --auto    …taking machine captions where there
                                          are no hand-written ones
python main.py add-channel <CH> --auto --dry-run   judge them, write nothing
python main.py status                     what is built, what is due
python main.py function-words             regenerate the closed-class review file
python main.py build-corpus tatoeba       analyse and cache a source (~7 min)
python main.py build-corpus subtitle      the smaller subtitle corpus (~15 s)
python main.py build-corpus subtitle --corrector llm    repair subtitles with the local model
python main.py build-corpus subtitle:auto    the machine-captioned videos, kept apart
python main.py build-corpus subtitle --min-words 7       raise the length floor
python main.py build-roadmap --steps 200  run the greedy walk
python main.py build-roadmap --source subtitle          study video subtitles only
python main.py fill-gaps                  generate the examples the corpus lacks
python main.py export-subtitles --source subtitle:llm   corrected subtitles as WebVTT
python main.py review                     terminal SRS session
python -m unittest discover -s tests -t .  run the tests
```

Rough costs, measured: `build-corpus tatoeba` 6 min (255,640 sentences, four
spaCy processes); `build-roadmap` about 11 s per 300 steps once the corpus is
cached, plus 10 s to load it.

## Why analysis is two passes

The German spaCy model is unreliable on a capitalised word at the start of a
sentence — German capitalises the first word of every sentence, so position
carries no information there. Two failures showed up directly in the roadmap:

- `Hast du Zeit?` lemmatises to `Hast`, while `Du hast Zeit` gives `haben`.
  One verb becomes several teachable units.
- `Gibst du das Tom?` tags the verb as a name and the name as a noun, which
  put `tom` in the roadmap at step 12 as the highest-gain word in the corpus.

A third failure is not positional at all: second-person forms like `willst`,
`gibst` and `nimmst` come back unreduced everywhere, and the stem vowel
changes, so no rule recovers the infinitive. spaCy ships a German lemma
lookup table that has them — but it is context-free and maps `sein` to `mein`
and `sie` to `ich`, so it is consulted only where the parser called the token
a verb, already failed on it, and the word is not itself an infinitive.
`data/lemma_overrides.txt` covers the handful the table misses; add a line
whenever an inflected form turns up in the roadmap.

Per-token output cannot be trusted, but the mistakes are a minority across a
quarter of a million sentences. So the first pass repairs what it can and
tallies evidence, and the second acts on the majority verdict: which lemma a
surface form usually gets, and whether a lemma is usually tagged as a name.
The vote needs a decisive margin, because some words really are two words —
`weiß` is both a colour and a form of `wissen`, and flattening that would be
worse than the failure it fixes.

## Putting the corrected subtitles back on the video

Correcting the subtitles produces text that is no longer the text the video
shipped with, so it has to be re-timed before it can be overlaid. Line-level
provenance is not enough: a subtitle row routinely holds the end of one
sentence and the start of the next —

```
6.44s  "die eine Seite der Medaille. Kaum jemand fragt: Was "
```

— so two corrected sentences would claim the same cue and stack on screen.

`SubtitleAligner` works a level down. Every word of the original gets a time
(each row's duration shared out by word length), the corrected words are
matched against them with a sequence matcher, and each sentence takes the span
of the original words it matched. The matcher tolerates the model's edits,
because most words survive a correction, and a sentence that matches nothing
falls back to the rows the model declared.

`export-subtitles` writes one `.vtt` per video — playable through a browser
`<track>` element, or by ffmpeg, mpv and VLC.

```
python main.py build-corpus subtitle --corrector llm
python main.py export-subtitles --source subtitle:llm --out out/subtitles
```

## Choosing a corpus

Every command that reads the corpus takes `--source`, naming one or more
builds. With no flag they use everything cached.

```
python main.py build-roadmap --source subtitle:llm   # real video subtitles only
python main.py review        --source subtitle:llm
python main.py build-roadmap --source tatoeba subtitle
```

Builds are named for how they were made, not just where they came from —
`subtitle` and `subtitle:llm` are different corpora and neither overwrites the
other.

## The known set

`data/known_words.txt` plus `data/function_words.txt`.

The **study list** — what to learn and in what order — is built from two
halves that each hold one of those answers. `words_4000.txt` is curated and
ranked but names words in their bare shape; `final_result.txt` knows the form
the matcher speaks (`etw./jdn. (Akk) haben`, not `haben`) in an order of its
own. They join on `final_result`'s first column, which is exactly what
`words_4000` lists — 4,095 of 4,096 lines match outright.

```
python main.py build-study-list      # writes data/study_list.txt
```

Merging also collapses duplicates: a word that appears both bare and under a
pattern keeps the pattern, since that is the more informative unit. The second exists
because the first is 771 entries of almost entirely content nouns — without it
`der`, `weil` and `nicht` count as unknown and the roadmap wastes its opening
on articles. Regenerate it with `function-words`, then strike anything you
don't know.

## Setup

```
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
uv pip install --python .venv/bin/python \
  https://github.com/explosion/spacy-models/releases/download/de_core_news_sm-3.8.0/de_core_news_sm-3.8.0-py3-none-any.whl
cp .env.example .env      # Postgres credentials
```

`spacy-lookups-data` is not optional in practice. Without it spaCy resolves
`musst` to `mussen` rather than `müssen`, so inflected forms stay separate
units from their infinitives. The analyser warns loudly if it is absent and
carries on, but a corpus built that way is measurably worse.

For sentence generation, add to `.env`:

```
LLM_BASE_URL=http://<tailscale-host>:11434/v1
LLM_MODEL=<model>
```

Without it, generation is skipped and everything else works.

## The local viewer

`python main.py serve` opens a page at `127.0.0.1:8765`: what to learn next,
the roadmap (searchable, filterable by words or patterns), where the roadmap
stops and what to go find material for, and the videos — with a box to paste
a new one into.

Reviewing lives on the command line only (`python main.py review`). In the
browser, the way you tell it you know something is the button on the thing
itself.

Roadmaps are stored per source, so the page can switch between studying the
video subtitles and studying everything without rebuilding either. The
examples shown beside a card come from whichever you have selected.

**What is next is computed live.** The page holds its own index rather than
reading a fixed sequence, so *I know this* takes effect on the next page load:
the word joins your known set, its card is dropped, and every sentence that
was waiting on it becomes readable. No rebuild. The stored roadmap stays as
the planned curriculum for the CLI and the export.

**Words can be watched being said.** Every subtitle sentence carries the
video and the second it starts, so *Watch it said* opens the clip at that
moment with the full transcript beside it. The transcript follows the video
and any line seeks it — the one place this project uses JavaScript, because
the player is the only thing that knows what time it is. The page still reads
and navigates with the script blocked.

The palette and structure come from a German school exercise book — cool
squared paper, königsblau ink, and the red margin rule dividing the rail of
step numbers from the reading column. German is set in a reading face and
English in a legibility face, one step down: the German is the material,
the English is scaffolding.

Server-rendered from the standard library — no framework, no JavaScript, no
build step. It binds to localhost only and has no authentication, so it must
not be exposed beyond this machine.

The first page load takes about fifteen seconds: it reads the whole cached
corpus and loads spaCy to resolve the vocabulary files. Everything after that
is instant.

## Layout

```
config.py     settings and tunables            context.py   object wiring
db/           read-only Postgres access        vocab/       units, word lists
corpus/       sources, correction, analysis    roadmap/     the greedy i+1 walk
srs/          SM-2 scheduling and review       generation/  local-model fallback
matcher/      vendored phrase_finder           commands/    one class per CLI verb
```

The Postgres database is read-only throughout — it belongs to `language-app`
— with exactly one exception: `add-video` writes a scraped video into its
tables, because that is where this project reads sentences from and a second
copy would drift. That path uses `WritableDatabase`, a separate class so the
exception is visible at the call site, and it commits only once the whole
video has landed.

`add-video` borrows language-app's own scraper rather than reimplementing it,
by path (`ingest/video.py` holds the path). It needs `yt-dlp`, `langdetect`,
`python-dotenv` and `scrapetube` on top of the usual requirements. After a
video lands, rebuild this project's cache to see it:

```
python main.py add-video https://www.youtube.com/watch?v=...
python main.py build-corpus subtitle
python main.py build-roadmap --source subtitle
```

All other state written by this project lives in `data/state.sqlite3`.
