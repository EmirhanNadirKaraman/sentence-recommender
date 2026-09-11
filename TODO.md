# Todo

Work that is understood but not done. Each entry says what, why, what it is
worth, and what would go wrong — so it can be picked up cold.

## Build speed

`build-corpus` is 828s over 1,128 videos. It is not paid per video: adding a
video goes through `CorpusUpdater.catch_up`, which parses only what is new. A
full rebuild is needed only when the analyser rules change, so these matter
about once a month — but when they matter, they cost a quarter of an hour.

Measured 2026-09-10, 8 cores:

    subtitle correction   342s   single process, before spaCy starts
    spaCy parse + units   486s   4 workers parsing, parent extracting
    total                 828s

### 1. Parallelise the subtitle correction — worth ~280s

`MergeCorrector.correct` is called once per video from `BuildCorpusCommand`.
It is pure Python, no model and no network, and each video is independent. A
`ProcessPoolExecutor` over videos should take 342s to something near 50s on
eight cores.

The care needed is ordering: the corpus is written in list order and the
filter carries de-duplication state that depends on what it has already seen
(`SentenceFilter.apply`, then `split`). Collect the per-video results and
reassemble them in the original video order before filtering, or the
duplicate-detection changes which of two identical lines survives — and the
build stops being reproducible.

Verify by rebuilding twice and diffing `sentence_units` — the row count and
the distinct unit count must both be identical to the serial build.

### 2. NER — NOT a free win, do not simply disable it

The pipeline loads `tok2vec, tagger, morphologizer, parser, lemmatizer,
attribute_ruler, ner` and NER is typically 15-25% of parse time. It looks like
dead weight because the analyser only wants tags and lemmas.

It is not. `matcher/phrase_finder.py:215` reads `child.ent_type_ == "PER"` to
decide whether a dependent is a person, which decides whether a phrase matches.
Disabling NER changes which patterns are extracted — a corpus change dressed
as a speed-up, and one that would be found weeks later as patterns quietly
missing.

If it is worth doing, do it deliberately: replace the `ent_type_` test with
something that does not need the model (`pos_ in ("PRON", "PROPN")` is already
half of that condition), measure how many phrase matches move, and treat it as
an analyser change with its own rebuild.

### 3. Phrase extraction is serial — the real ceiling

`analyze_all` forks four workers for the parse and then runs `_units` and
phrase extraction in the parent, one Doc at a time. Parent CPU was 5:52
against ~1:47 per worker: the parent is the bottleneck, so a bigger
`batch_size` buys nothing. Moving extraction into the workers means shipping
`Doc`s or re-parsing there, and is the largest of these three by far.

## Vocabulary

### 4. Adjectives sitting in `function_words.txt`

`stressig`, `interessante`, `alt`, `fest`, `bereit`, `voll`, `übrig`, `pack`,
`all`, `namens` are in the closed-class file and are not closed-class. They are
therefore assumed known on the strength of a category they do not belong to.
`db/word_repo.function_words` selects by tag, so either the tags are wrong for
these or the tag set is too wide. Decide per word rather than by rule; there
are about ten.

### 5. `--from known` has never been run

The 771 entries of `known_words.txt` are an A1/A2 exam wordlist that arrived
with the project skeleton and has never been checked against this reader. 22
words are confirmed, 0 denied. Until a few hundred are answered there is no
way to tell whether the list is a good prior or fiction, and that answer
decides whether it is worth keeping at all.

## Material

### 6. Subscribe to channels, or pick genres, and prefer their videos

The reels and the video roadmap rank every video in the catalogue by what it
teaches and how well it plays. Nothing says whose videos the reader would
actually sit through, and a channel they like is a stronger reason to watch
than a tenth of a sentence a minute.

The blocker is data, not design. Of 1,134 German videos, 17 know their
channel: `channel_id` has only been written since 8e7a146, and the rest
cannot be backfilled from anything stored — it is one yt-dlp metadata call
per video, paced the way `hunt` paces its searches. `video.category` is no
substitute for a genre: 1,155 of 1,382 are YouTube's "Education".

Once the column is filled: a subscription is a reader's judgement, so it
lives in `state.sqlite3` beside `known_units`, not in `channel.active`,
which is the scraper's flag. Apply it as a weight in `_score_video` and a
tie-break in `VideoWalk.build`, never as a filter — the walk stops when
nothing left teaches, and a walk over one channel is a different curriculum,
not a preferred one. Say what the preference costs in sentences taught.

### 7. Auto-generated captions, repaired by the local model

Ingest refuses auto-generated captions (`ingest/video.py:173`, and
language-app's fetcher before it) because ASR mangles the endings a learner
is studying. So all 1,382 videos are `transcript_source='manual'`, and manual
German subtitles are the scarce thing: `hunt` discards most of what it finds
for lacking them, and the 190-channel queue would grow the pool if auto
tracks were acceptable.

The repair already exists — `build-corpus subtitle --corrector llm`, cached
as its own build `subtitle:llm`, with a retention check and a per-chunk
fallback — but no `subtitle:llm` build has ever been made, so whether a
local model can put the endings back is unmeasured.

Measure before opening the gate, and the ground truth is free: videos that
carry both a manual and an auto track. Fetch the auto track for fifty, run
it through the corrector, and compare the *unit set* from `UnitAnalyzer`
against the manual track's — units are what the roadmap consumes, and
`MIN_RETENTION` catches a summary but not `dem` → `den`, which is the
failure that matters. At scale: 248,598 German subtitle rows at 25 rows a
call is ~10,000 model calls, hours on a local model, and nothing caches a
reply, so a crash at video 900 costs the first 899. Keep auto videos in
their own build and `transcript_source='auto'`, so the reader can see
which text a machine wrote twice.

### 8. Backfill `channel_id` on the 1,117 videos that lack it

Item 6 needs this and cannot start without it, which is why it is its own
entry rather than a clause inside one. 1,117 of 1,382 videos have a null
`channel_id`, and every one of them is German — the non-German rows came
from upstream with theirs already set.

Nothing stored can supply it. The channel was never written down, so each
video needs one `pipeline.fetch_video_metadata` call, which already returns
`channel_id` and `channel_name` beside the title; `pipeline.upsert_channel`
turns that into a row id and is idempotent — it keeps a name already
recorded rather than overwriting it. Both were exercised on the live schema
in 8e7a146, so the pieces exist and the work is a loop and a pace.

The pace is the whole difficulty. On 2026-09-11 five metadata calls five
seconds apart drew "The page needs to be reloaded" from YouTube, and cookies
do not help — they answer the sign-in wall, not burst throttling. At 1,117
videos this is a long, resumable job: write each result as it arrives rather
than at the end, skip videos that already have a channel, and treat a
throttle as weather, never as an answer.

That last point is the trap, and it has already been fallen into once. An
attempt that could not be completed was recorded as a verdict and settled
permanently, writing off nine videos that were never checked — one of which
had been scraped successfully minutes earlier. `AttemptLog.classify` now
returns `unfetchable` for a refusal that explains nothing; a backfill needs
the same distinction or it will quietly mark rows as having no channel.

Worth: 1,117 videos' worth of provenance, and the only thing standing
between here and item 6. Also makes `add-channel` able to say what it
already holds from a channel before fetching anything.

## Word lists

### 9. Lists built by searching, and a page that can choose between them

The roadmap's aim is a file: `data/study_list.txt`, or `--goals-file PATH`
on the command line only. Wanted: search the vocabulary with a box that
tolerates misspelling, tick words, name the list; then choose on the page
which list the plan chases, and whether the walk may pay two words at once.

The tightest constraint is naming, not search. A plan is stored under a
label composed from its builds, `:good`, `:strict`/`:list`, `:goals` and a
non-default list's stem (`commands/build_roadmap.py:74-84`), and `save`
deletes whatever that label held. The label says nothing about `--relax`,
so a relaxed build silently overwrites the plain one; and `_stored_label`
looks only for the default names, so a plan aimed at any other list cannot
be reached from the page. Until the label names both, the switches have
nothing to switch between.

Then: lists are judgements, so a `word_list` table in `state.sqlite3` with
`GoalList` reading from it as well as from a file. The walk is minutes and
cannot run inside a request; queue it the way `_queue_rescore` does. Search
the build's 35k lemma units in memory — a trigram index is thirty lines —
rather than `pg_trgm`, which migration dd0d9cf4b307 declined because
nothing issued a fuzzy query; the first one that does should reopen that
decision, not step past it. i+2 keeps `--relax`'s meaning, only at the wall
(weighing pairs throughout degrades the whole sequence), and the page shows
a relaxed step's `beside` word, which is already stored.

## Other people

### 10. Letting friends run it

Two questions, in order. First, the state is one reader's: `known_units`,
`cards`, `roadmap`, `video_score` and the rest of `state.sqlite3` have no
user column, so a second person's *I know this* marks it known for the
first. Second, the front door: `serve` binds loopback with no auth, and
IOS.md chose Tailscale over a VPS because membership is the auth.

The fork:

- **Each friend runs their own copy.** No refactor. Ship a `pg_dump` of the
  catalogue and analysed corpus so nobody scrapes or waits 828s for a build,
  pin `spacy`, the model and `spacy-lookups-data`, and say 4 GB. Only for
  friends who will install Postgres.
- **One instance, several readers.** A user column on every judgement table
  and on the caches keyed by a known set, then identity from the door: a
  tailnet invite (membership), or Cloudflare Tunnel behind Cloudflare
  Access (an identity header the server may trust only because it is
  reachable through the tunnel alone). IOS.md's objection was to a Tunnel
  with nothing in front of it. Seat limits on either need checking.

Cloudflare does not rent servers; the server is the always-on Mac or a 4 GB
VPS, and that is the last decision here, not the first.

## Read speed

A cold page pays a corpus load; a warm one pays nothing. `/blocked` is 4.5s
cold and 3ms after, and every entry here is about that first number.

Measured 2026-09-11, after 7b739a3 moved unit filtering into the read:

    corpus(strict=True)            3.66s   169,155 sentences
      of which unit rows in SQL    1.54s   1,742,479 rows
      the rest is object building  ~2s     Sentence objects, interned units
    CorpusIndex                    0.58s
    cold /blocked                  4.54s

### 11. The load is now object building, not querying

1.54s of the 3.66s is 1.74M unit rows crossing the wire; most of the balance
is assembling 169,155 `Sentence` objects and interning their units. There is
no third thing left — the filtering that used to cost 3.35s is gone.

The tempting number is the SQL that computes every sentence's unknown count
directly: 1.6s, and verified identical to Python on all 169,155. It is not a
drop-in. `CorpusIndex.learn` decrements `_unknown[position]` as the walk
proceeds, thousands of times, so the walk needs the sentences in memory
whatever the storage is. That query is the right shape for a design where the
walk is *also* SQL, and quoting it as an available saving is how this gets
started and abandoned.

Cheaper first: find out whether the pages that pay this actually need it —
see 12.

### 12. Do the stored-plan pages need an index at all?

`/roadmap` and `/quiz` read a plan that was already walked and stored. If
`Viewer.scope` builds a `CorpusIndex` for them regardless, they are paying a
full corpus load and a 0.58s index to read rows they could read directly.

Worth the whole cold cost on two of the five pages, and the check is an
afternoon: follow `scope`'s callers and see which of them ever walk. If none
do, the fix is a narrower accessor, not an optimisation.

What would go wrong: `scope` is cached per source and counting mode, so a
page that looks cheap in isolation may be warming the index another page then
uses. Measure the pair, not the page.

### 13. What the 84,849 overlay sentences cost

84,849 of 254,005 sentences are `teachable = False` — kept so the transcript
panel beside the player has no holes. Every study query filters them out in
SQL (`teachable_only=True`), so they are not being assembled into objects;
what they cost is table and index size, and rows the planner walks past.

Measure before moving them: a separate table would make the overlay a second
query and a join, which is the panel's whole cost. The answer may well be
that they are fine where they are — but 33% of the corpus existing for one
panel is worth knowing the price of.

### 14. `roadmap_example` is 65% repeated text

114,473 rows carrying 40,062 distinct texts, inside a `state.sqlite3` that is
now 63 MB total — the corpus having left for Postgres.

This was measured once and the denormalisation was kept deliberately: 29%
faster reads for 26% more space, and the duplicate text is a snapshot of what
a step showed rather than redundancy. Reopen it only with a reason the
earlier measurement did not cover — the file shrinking by 150 MB changes the
ratio the decision rested on, so "it is most of what is left" is such a
reason, and "it looks duplicated" is not.
