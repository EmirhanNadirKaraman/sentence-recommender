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
- **Generated** — a local model fills gaps where no natural i+1 sentence
  exists for a unit. Every generated sentence is re-analysed and kept only if
  its unknowns are exactly the target.

## Commands

```
python main.py status                     what is built, what is due
python main.py function-words             regenerate the closed-class review file
python main.py build-corpus tatoeba       analyse and cache a source (~7 min)
python main.py build-corpus subtitle      the smaller subtitle corpus (~15 s)
python main.py build-corpus subtitle --corrector llm    repair subtitles with the local model
python main.py build-roadmap --steps 200  run the greedy walk
python main.py build-roadmap --source subtitle:llm      study real video subtitles only
python main.py fill-gaps                  generate the examples the corpus lacks
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

Per-token output cannot be trusted, but the mistakes are a minority across a
quarter of a million sentences. So the first pass tallies evidence and the
second acts on the majority verdict: which lemma a surface form usually gets,
and whether a lemma is usually tagged as a name. On the subtitle corpus this
takes `tom`, `hast`, `bist` and `gibst` from teachable units to zero.

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

`data/known_words.txt` plus `data/function_words.txt`. The second exists
because the first is 771 entries of almost entirely content nouns — without it
`der`, `weil` and `nicht` count as unknown and the roadmap wastes its opening
on articles. Regenerate it with `function-words`, then strike anything you
don't know.

## Setup

```
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python psycopg2-binary spacy requests
uv pip install --python .venv/bin/python \
  https://github.com/explosion/spacy-models/releases/download/de_core_news_sm-3.8.0/de_core_news_sm-3.8.0-py3-none-any.whl
cp .env.example .env      # Postgres credentials
```

For sentence generation, add to `.env`:

```
LLM_BASE_URL=http://<tailscale-host>:11434/v1
LLM_MODEL=<model>
```

Without it, generation is skipped and everything else works.

## Layout

```
config.py     settings and tunables            context.py   object wiring
db/           read-only Postgres access        vocab/       units, word lists
corpus/       sources, correction, analysis    roadmap/     the greedy i+1 walk
srs/          SM-2 scheduling and review       generation/  local-model fallback
matcher/      vendored phrase_finder           commands/    one class per CLI verb
```

The Postgres database is read-only throughout — it belongs to `language-app`.
All state written by this project lives in `data/state.sqlite3`.
