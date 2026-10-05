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
python main.py translate-sentences        an English line for every roadmap sentence
python main.py translate-sentences --all  …and for the rest of the corpus
python main.py export-subtitles --source subtitle:llm   corrected subtitles as WebVTT
python main.py review                     terminal SRS session
python main.py mcp-serve                  the roadmap and the reviews as MCP tools
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
  https://github.com/explosion/spacy-models/releases/download/de_core_news_md-3.8.0/de_core_news_md-3.8.0-py3-none-any.whl
cp .env.example .env      # Postgres credentials
```

The medium model, not the small one. The matcher loads `de_core_news_md`
by name, so `sm` does not stand in for it: `spacy.load` raises and the
first parse fails.

`spacy-lookups-data` is not optional in practice. Without it spaCy resolves
`musst` to `mussen` rather than `müssen`, so inflected forms stay separate
units from their infinitives. The analyser warns loudly if it is absent and
carries on, but a corpus built that way is measurably worse.

For sentence generation and the English glosses, add to `.env`:

```
LLM_BASE_URL=http://<tailscale-host>:11434/v1
LLM_MODEL=<model>
```

Any OpenAI-compatible server does: Ollama, LM Studio, llama.cpp, vLLM. The
URL almost always has to end in `/v1`.

Reached over a public tunnel — Cloudflare's, say — the endpoint is on the
open internet and wants a secret too:

```
LLM_BASE_URL=https://<name>.trycloudflare.com/v1
LLM_MODEL=<model>
LLM_API_KEY=<the password>
LLM_AUTH=bearer
```

`bearer` is the default and is what an OpenAI-compatible server means by an
API key. Two other shapes are supported for tunnels fronted differently:
`LLM_AUTH=basic` (with `LLM_USER`) for HTTP basic auth, and
`LLM_AUTH=header` (with `LLM_AUTH_HEADER`, default `CF-Access-Client-Secret`)
for a Cloudflare Access service token.

Check it before relying on it:

```
python main.py check-model
```

That reports what the endpoint serves, says plainly which auth shape it
wants if the secret is refused, and times one round trip so a run over the
whole deck can be estimated from a measurement rather than a guess. `.env`
is gitignored, and the key is never printed or logged.

Without any of it, generation is skipped and everything else works.

`bundle-deck --video` needs ffmpeg, and only that command does:

```
brew install ffmpeg
```

Without it the episodes and their chapter lists are still written; only the
MP4s are skipped, and the command says so rather than failing late.

Create the database itself once, and build its schema:

```
createdb sentence_recommender
alembic upgrade head
```

That leaves you with an empty catalogue. Filling it means scraping subtitles
and parsing them, which is the expensive part — so if someone already has a
corpus, take theirs.

## Moving the corpus to another machine

Not by copying files. Postgres is a server with its own storage layout, and
most of what is on disk is index rather than data: 3,315 MB of database is a
162 MB dump, because `pg_dump` writes the *definition* of an index and the
restore rebuilds it.

On the machine that has one:

```
pg_dump -Fc -Z6 --exclude-schema=accounts --exclude-schema='reader*' \
  -f corpus.dump sentence_recommender
```

On the machine that wants it, after the Setup above but *instead of*
`alembic upgrade head` — the dump carries the schema and the
`alembic_version` row with it, so migrations land in step:

```
createdb sentence_recommender
pg_restore --no-owner --role=$(whoami) -d sentence_recommender corpus.dump
```

`--no-owner` is not optional unless both machines happen to use the same
database role. The dump names its owner in a hundred places and the restore
reports an error at every one of them otherwise.

**Send nothing else.** The two `--exclude-schema` flags are what keep the
dump to the corpus. `accounts` holds the readers' password hashes and the key
their sessions are signed with. `reader`, and every `reader_<name>`, is one
person's answers — the words they have marked known, their review cards,
their stored roadmaps, what they think of which channel — made empty on
first use wherever the corpus lands. Nobody else's copy is useful, and it is
nobody else's business. A backup for yourself is the same command without
the two flags. `data/tatoeba.sqlite3` predates the move to Postgres and
nothing reads it. `.env` holds credentials; `.env.example` is the one to
copy.

What arrives is a catalogue and an analysed corpus, so the receiving machine
can serve pages immediately. It still needs its own roadmap: plans live in
the reader's schema and are not in the dump at all. Run `build-roadmap`
once after restoring — it walks against your known set, which is why the
plans are not the shareable part.

## Or with Docker

For someone handed a dump, this is the whole setup — with Docker Desktop
running, which it is not just because it is installed:

```
mkdir -p dump && cp /wherever/corpus.dump dump/
docker compose up
```

Then `http://127.0.0.1:8765`. Postgres comes up at a pinned version, the
database and role are created, the dump is restored into it, and the app
image carries `de_core_news_md`. Every mistake the Setup section above warns
about is one that cannot be made here.

The restore runs only on an empty data directory, so it happens once. To do
it again — a newer dump, or a bad one — `docker compose down -v` and up
again. A 162 MB dump takes about two minutes, indexes and all.

What you know, your cards and your roadmaps live in the database, in the
`pgdata` volume, so they survive a rebuilt image — and `docker compose down
-v` deletes them along with the corpus. Before restoring again that way,
take a dump without the excludes above. `./data` is mounted from the host
for the files you edit by hand: the word lists. The app publishes on
`127.0.0.1` only; before anyone else reaches it, give the first reader a
password (see "Readers") and put a TLS proxy in front.

The dump is never baked into an image and no link to one belongs in this
repo. `dump/` is ignored; the file is something you are handed.

**What the container cannot do is scrape.** `add-video`, `add-channel` and
`hunt` hand yt-dlp the cookies of a browser signed in on the host, which is
what gets past "Sign in to confirm you're not a bot" — and there is no
browser in a container. Everything that studies a corpus already built
(`serve`, `build-roadmap`, `review`, `blockers`) needs neither cookies nor
network. So: containers for reading someone else's corpus, a virtualenv for
growing your own.

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
build step. It binds to localhost only. Until a reader has a password it has
no door at all, so it must not be exposed beyond this machine before then
(see "Readers").

The first page load takes about fifteen seconds: it reads the whole cached
corpus and loads spaCy to resolve the vocabulary files. Everything after that
is instant.

## Readers

One installation can serve several people, each learning one language —
German, or English — with their own known words, cards, plans and
judgements. The pages ask who is reading.

The first reader is whoever's files are at the top of `data/`. Registering
them moves nothing; it gives them a name and a password:

```
python main.py reader add emir --home data
python main.py reader password emir
```

From then on every page wants a password, and the first reader can invite
others, from the account page or from here:

```
python main.py reader invite --language en
```

That prints a `/signup?invite=…` link, good once and for seven days. Whoever
opens it on this server's address picks a name and a password, and starts
from nothing: what they know is what they mark as they read. `--native`
names the language their translations are made in.

Every command takes `--reader NAME` after its own name, and works on that
reader's state and their language's corpus; without it, the first reader's.
English has a model and a corpus of its own:

```
uv pip install --python .venv/bin/python \
  https://github.com/explosion/spacy-models/releases/download/en_core_web_md-3.8.0/en_core_web_md-3.8.0-py3-none-any.whl
python main.py add-channel @HANDLE --reader ahmet
python main.py build-corpus subtitle --reader ahmet
```

Where it all lives, in the one database:

| schema | what |
|---|---|
| `public` | the German catalogue and corpus |
| `en` | the same tables, for English |
| `accounts` | who the readers are: names, languages, password hashes, the Google accounts that sign them in, open invitations, the key sessions are signed with |
| `reader` | the first reader's state: known words, cards, plans, the judge's answers, the glosses paid for |
| `reader_<name>` | the same, for each reader added since |

### Signing in with Google

Three lines in `.env` put a Google button on every door, and let anyone
with a Google account make an account here on their own, no invitation
needed:

```
GOOGLE_CLIENT_ID=<…>.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=<…>
PUBLIC_URL=https://<machine>.<tailnet>.ts.net
```

The first two come from the Google Cloud console
(console.cloud.google.com):

1. Make a project. Under *APIs & Services → OAuth consent screen*, choose
   *External* and give it a name and your address. While its publishing
   status is *Testing*, only the test users listed there can sign in;
   publish it for anyone with a Google account. It asks for nothing but
   a name and an address (`openid email`).
2. Under *APIs & Services → Credentials*, create an *OAuth client ID* of
   type *Web application*. Add `PUBLIC_URL` followed by
   `/auth/google/callback` under *Authorized redirect URIs*, character for
   character, and copy the client ID and secret into `.env`.
3. Restart `serve`.

Try it first with `PUBLIC_URL=http://localhost:8765` and that address's
callback registered: the console takes a plain-HTTP address for
`localhost` only. Behind `tailscale serve` or another TLS proxy, use the
HTTPS address; the console says when you add it whether it accepts that
host. A sign-in begun on any other address is sent to `PUBLIC_URL` first,
because Google answers there and nowhere else.

A reader is known by Google's own id for their account, never by its
address. Someone with a password can link a Google account in Settings,
and unlink it again; someone who signed up with Google can add a password
there.

With strangers able to read here, the owner is the only one who:

- **adds videos and channels.** That scrapes YouTube with the owner's
  browser cookies, into the corpus every reader of the language shares.
- **recalculates plans.** There is one set of plan files, and every
  reader's Plan page shows them: the owner's plans, from the owner's words.
- **puts sentences into the corpus.** Anyone else's sentences on Mine stay
  in their own schema.

Everyone else gets sixty model calls an hour: a gloss asked for the first
time, a sentence tried, a sentence put into the other language. They can
keep one saved word list open besides their own. `SIGNUP_LIMIT` (default
10, 0 closes sign-up) caps how many sign up on their own; invitations do
not count. A reader reading holds about 250 MB.
`python main.py reader list` says who joined how;
`python main.py reader remove NAME` deletes a reader and everything they
stored, and never the owner.

A session is a signed cookie. Behind `tailscale serve` or any TLS proxy
that sets `X-Forwarded-Proto`, it is marked `Secure`; a form posted from
anywhere but this site is refused; changing a password signs every other
device out.

**An installation from before the readers** kept all of this in
`data/state.sqlite3`, and the registry in `data/readers/readers.json`. Move
it once, with `serve` and `mcp-serve` stopped and a backup taken:

```
python main.py migrate-state --dry-run
python main.py migrate-state
```

Every table goes across by `COPY`, in one transaction, and is compared row
by row by hash before it commits: a mismatch commits nothing. The files are
renamed `*.migrated`, never deleted. Half a gigabyte of state took a minute
or so here.

## Using it from Claude

`python main.py mcp-serve` is the project as an MCP server: the same
questions the viewer answers, published as tools an agent can call. A client
that speaks MCP — Claude Code, Claude Desktop — launches the command itself,
reads the tool list, and from then on can run a tutoring session against
your own roadmap without any code written on its side.

| tool | what it does |
|---|---|
| `next_up` | the next i+1 step: the sentence, the unit it teaches, its deck |
| `mark_known` | *I know this* — or `pass` to set it aside, `undo` to take it back |
| `due_cards` / `grade` | the review queue, and SM-2 rescheduling after an answer |
| `check_word` | why a word on the study list is or is not being taught |
| `status` | what is built and what is due |

Beside the tools, `roadmap://<label>` reads a whole stored plan as a
resource, and the `tutor` prompt starts a reading session (in Claude Code,
`/mcp__sentence-recommender__tutor`).

`.mcp.json` at the root registers it for Claude Code, under `.venv`'s
interpreter for the reason above; the first `claude` run in this folder asks
you to approve it, and `claude mcp list` shows it connected from then on.
To reach it from any other folder, or from Claude Desktop, register it by
absolute path instead:

```
claude mcp add sentence-recommender -s user -- \
    "$PWD/.venv/bin/python" "$PWD/main.py" mcp-serve
```

To poke at the tools without a model in the loop:

```
npx @modelcontextprotocol/inspector .venv/bin/python main.py mcp-serve
```

The transport is stdio: the client owns the process and there is no port,
so nothing is exposed. `next_up` answers from the stored plan when one
matches the rules in force and walks the corpus otherwise, which is the
same fifteen seconds the first page load pays. The server keeps that index
for as long as the client keeps it running.

## Tests

```
createdb -h localhost -U postgres -O <DB_USER> sentence_recommender_test
PYTHONPATH=. .venv/bin/python -m pytest -q
```

The stores' tests need a database, and never get the real one: each test
makes a schema of its own in `sentence_recommender_test` and drops it after,
and the helper refuses to drop anything else. The database is made once, by
a role that may create one, owned by the everyday role in `.env`.
`TEST_DB_NAME` names another.

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
by path (`ingest/video.py` holds the path) — all but the caption fetch, which
asks YouTube's player API directly (`ingest/captions.py`). It needs
`yt-dlp`, `langdetect`, `python-dotenv` and `scrapetube` on top of the usual
requirements. After a video lands, rebuild this project's cache to see it:

```
python main.py add-video https://www.youtube.com/watch?v=...
python main.py build-corpus subtitle
python main.py build-roadmap --source subtitle
```

Everything a reader does lives in their own schema, `reader` or
`reader_<name>`, and who the readers are in `accounts` (see "Readers").
