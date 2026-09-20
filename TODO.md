# Todo

Work that is understood but not done. Each entry says what, why, what it is
worth, and what would go wrong — so it can be picked up cold.

## Build speed

`build-corpus` is 828s over 1,128 videos. It is not paid per video: adding a
video goes through `CorpusUpdater.catch_up`, which parses only what is new. A
full rebuild is needed only when the analyser rules change, so these matter
about once a month — but when they matter, they cost a quarter of an hour.

Measured 2026-09-10, 8 cores — **and not to be trusted**:

    subtitle correction   342s   single process, before spaCy starts
    spaCy parse + units   486s   4 workers parsing, parent extracting
    total                 828s

Re-measured 2026-09-11 on a quiet machine, the first line is 125s, and the
parent/worker split the third entry rests on comes back inverted. Three
figures from that session have now been about three times too large. Treat
the table as a shape, not as numbers, and re-measure before designing
against any line of it.

### 1. Parallelise the subtitle correction — DONE, worth 50s not 280s

Done, and both halves of the estimate were wrong.

`build-corpus --workers N` spreads `MergeCorrector.correct` plus the aligner
over processes, merge path only: `LLMCorrector` counts chunks, fallbacks and
rejections on itself (`corpus/llm_corrector.py:68-70`), and a worker would
keep its own copy and lose them. `executor.map` yields in the order it was
given, which is all reproducibility needs here.

Measured over all 1,235 videos and 271,414 lines:

```
  serial        125.5s     215,437 sentences
  4 workers      75.3s     215,437 sentences     1.67x
```

Identical, and checked harder than this entry asked. "Diff `sentence_units`"
needs two full builds; comparing the sentence stream itself, in order, before
the filter sees it, tests the property actually at risk — the filter's
duplicate check carries state along the list, so a different order changes
which of two identical lines survives.

**Why it is 1.67x and not the 6.8x this predicted: macOS Python does not
fork, it spawns.** Every worker re-imports the package and every video's
lines are pickled across, so six workers on six videos cost 0.96s before
doing any work. The curve flattens early — 2 workers 1.15x, 4 workers 1.39x,
6 workers 1.45x on a 120-video sample — and past four the start-up eats the
gain. Anything here that assumes a free fork is wrong on this machine.

**And the 342s was not real.** Correction is 125.5s. The measurement above
it, and very likely the whole 828s table, was taken on a loaded machine —
the same mistake `scratchpad`'s plan file records at length, where page
timings taken at load average 50 were wrong by a factor of twenty-five.
Re-measure the table on a quiet machine before trusting any line of it,
including the ones under 2 and 3.

### 2. NER — DONE, and it was a correctness fix as much as a speed-up

Still not a free win, and still an analyser change. But both numbers in the
original entry were guesses, and both were wrong in the direction that
matters.

**NER is 44% of parse time, not 15-25%.** 4,000 sentences parse in 12.83s
with it and 7.25s without.

**It decides 11 of 3,251 object tokens** — 0.338%. `get_object_token` asks
`pos_ in ("PRON","PROPN") or ent_type_ == "PER"`, and a person's name is
normally PROPN already, so NER only speaks where a token is PER and neither
PRON nor PROPN.

Read the eleven and the picture sharpens further:

```
  Herrn  Kraft  Herrn  Mutter  Sohn  Sohn  Herrn  Bruder  Bruder   people
  Straße  Bescheid                                                 not people
```

Nine right, two wrong. So the model is bought for nine correct decisions in
3,251, and it introduces two errors of its own — `Straße` and `Bescheid`
become `jdn.`

**The obvious replacement is better than either option.** Nine of the nine
are titles and kinship terms — `Herr`, `Mutter`, `Sohn`, `Bruder`. A short
list of person nouns catches them without a model *and* does not invent the
other two. That beats keeping NER and beats the bare `pos_` test this entry
proposed, which would have lost all nine.

Done, with the person-noun list rather than the `pos_`-only test — and it
turned out to be the opposite of the risk this entry was written around.
Against the model on the same 3,251 object tokens:

```
  3,153  agree
     95  people under the list that NER never saw
      3  people under NER that the list does not
```

NER fires on *named* entities, so ordinary person nouns were being called
things all along. `Frauen unterstützen` was `etw. unterstützen` and is now
`jdn.`; `den Menschen erklären` was `etw.` and is now `jdm.` Every one of
ten spot-checked is a correction. Of the three going the other way two were
NER's own mistakes, and the real loss is a surname that is also a common
noun, which no word list can catch.

Carried out as the entry required: fingerprint bumped (`phrase_finder.py` is
in `SOURCES`), both corpora rebuilt, all ten roadmaps re-walked, both reports
regenerated.

```
  subtitle     215,437 sentences   41,173 units   683s
  transcript    53,134 sentences   19,211 units   205s
  units, both    49,262            was 46,433
  b1 out of reach     9            was 11
  study list        347            was 341
```

The unit count rises because the person/thing split separates blueprints
that used to collapse together — 500 patterns now name a person against 442
naming only a thing — and that is also why the study list ticks up six: some
goals map to a more specific and therefore rarer pattern. b1 improves. The
trade is a slightly harder corpus that is describing German more accurately,
bought alongside 51% of parse time.

### 3. Phrase extraction is serial — measured, and it is not the ceiling

The premise is inverted. This says the parent is the bottleneck and calls
itself "the largest of these three by far". Measured over 4,000 sentences,
single process:

```
  parse                    13.59s    88%
  _units (parent)           1.91s    12%
  _normalise etc (parent)   0.01s     0%
```

The parent does 12% of the work, not the bulk of it. Give the parse four
workers and its wall time falls to about 3.4s against 1.9s of serial parent
— so the parent is 36% of the wall clock and the parse is still 64%.

That caps the prize. Moving extraction into the workers can remove at most
that 36%, and on this platform it has to get `Doc`s there to do it —
Python spawns rather than forks here (see 1), so they would be pickled
whole, and re-parsing in the worker would spend more than the 36% it saves.

**The cheaper lever is 2.** NER is 44% of parse time and parse is 64% of the
wall, so dropping it is worth about 28% of the analysis phase — against 36%
for a restructure that fights the process model, and it is a constant and a
word list rather than a redesign. Do 2 first, then re-measure this; the
ratio will have moved and this entry's answer may change with it.

One caveat on the numbers above: they are single-process CPU, and the
original 5:52-against-1:47 was taken with four workers running. That does
not rescue the premise — the per-sentence costs are what they are — but it
is the third figure from that session to come back roughly three times too
large, after 342s of correction that is 125s and a parent cost that is a
seventh of the parse rather than triple it.

## Vocabulary

### 4. Adjectives sitting in `function_words.txt` — DONE

Neither the tags nor the tag set, in the end: the query admits a lemma if
*any* of its rows carries a closed-class tag, however rare, so a single
mis-tagged form was enough. `alt` is ADJA fifteen times and VMFIN twice, and
the two VMFIN rows are `ältesten`.

Decided per word against the corpus tags, as this said to. Ten struck —
`alt`, `hoch`, `voll`, `weg`, `fest`, `übrig`, `bereit`, `stressig`,
`interessante`, `pack`. Five left live because they earn it whatever their
frequency: `all` and `namens` are a real indefinite pronoun and a real
preposition, `doch` is a modal particle and is tagged ADV as modal particles
are, and `anderer` and `irgendjemand` are a determiner and a pronoun.

`alt`, `weg`, `hoch` and `doch` were in `known_words.txt` anyway, so striking
them removed a wrong reason rather than a right answer. The other six become
teachable, which is the point.

A rule was available and refused: "closed-class tags carry most of the
frequency" catches nine of these and misses `stressig`, `pack`, `übrig` and
`bereit`, whose frequency rows are too sparse to decide anything.

### 5. `--from known` has never been run

The 771 entries of `known_words.txt` are an A1/A2 exam wordlist that arrived
with the project skeleton and has never been checked against this reader. 22
words are confirmed, 0 denied. Until a few hundred are answered there is no
way to tell whether the list is a good prior or fiction, and that answer
decides whether it is worth keeping at all.

## Material

### 6. Subscribe to channels — DONE. Genres still have no data

The reels and the video roadmap rank every video in the catalogue by what it
teaches and how well it plays. Nothing said whose videos the reader would
actually sit through, and a channel they like is a stronger reason to watch
than a tenth of a sentence a minute.

**Channels are built.** Two buttons above the reel, More of this and Less of
this. The preference lives in `state.sqlite3` beside `known_units`, not in
`channel.active` which is the scraper's flag, and it is keyed by YouTube's
channel id rather than the catalogue's integer — `sync-catalogue` refills
that table wholesale, so a preference pinned to a row number moves to another
channel the next time the numbering does.

Applied two ways, neither of them a filter:

- **A weight when the feed is ordered**, x2 up and x0.25 down, and never in
  the stored score. What you think of a channel is not a property of its
  videos, so the cache stays true and saying something costs no rescore —
  which is why `SCORE_VERSION` did not have to move. Measured end to end:
  setting the top channel aside took it from 0.0733 to 0.0183, subscribing
  to the next took it from 0.0107 to 0.0214, and they swapped. The demoted
  channel stayed in the feed one place down.
- **A tie-break in `VideoWalk.build`**, because a walk over one channel is a
  different curriculum and not a preferred one. Taste may settle two videos
  that teach comparably and may never lift a worse one over a better.

"Comparably" had to be banded. Exact equality would never fire: across 1,971
videos over the line floor there are five tied groups, and 421 of the 429
videos in them teach nothing, which the walk breaks out before reaching. The
rates are packed instead — 1,459 of the 1,550 videos that teach anything sit
within 0.01 sentences a minute of the next. So the rate is rounded to two
decimals before it is compared. Not one: at a tenth of a sentence a minute
1,546 of those 1,550 share a band and taste would decide nearly the whole
order, which is a weight wearing a tie-break's name. Two leaves 214 bands.

**The catalogue is far less lopsided than this item assumed**, which matters
because the old argument was that a preference had teeth only on the long
tail. All 2,887 videos carry a `channel_id` across 368 named channels (item
8), against 1,483 and 280 when this was written:

```
  Like Germans                 692
  MrWissen2Go                  400
  Deutsch mit Rieke            288
  UNED                         246
  MrWissen2go Geschichte       186
  Dinge Erklärt – Kurzgesagt   163
  ... 362 more channels
```

The top two are 38% of it, where they were 63%. Preferring one of them is now
worth something.

**Genres are still blocked on the same thing.** `video.category` is no
substitute: 1,997 of 2,887 are YouTube's "Education", 69% in one of eight
buckets — better than the 84% this item recorded, and still not a genre. It
would need a signal that does not exist yet, from the channel or the title or
the corpus itself, and none of that is worth guessing at.

**Still owed:** say what the preference costs in sentences taught. Setting a
channel aside changes a curriculum and nothing reports by how much.

### 7. Auto-generated captions — GATE OPEN, behind a quality test

Ingest refused auto-generated captions (`ingest/video.py`, and language-app's
fetcher before it) because ASR mangles the endings a learner is studying. So
all 1,382 videos were `transcript_source='manual'`, and manual German
subtitles are the scarce thing: `hunt` discards most of what it finds for
lacking them, and the 190-channel queue would grow the pool if auto tracks
were acceptable.

**`add-videos --auto` and `add-channel --auto` now take one where there is no
hand-written track at all** — never instead of one, because of the
measurement below. It lands as `transcript_source='auto'` in its own build,
`subtitle:auto`, and the Studying switch is the filter: pick *video
subtitles* and no machine caption is counted, ranked or taught anywhere.
Videos that came in that way carry an `auto` mark on the catalogue and a
*captions: machine* cell on the reel.

The rest of this entry is the measurement that decided the shape, and it is
worth keeping in mind which question it answers.

The repair already exists — `build-corpus subtitle --corrector llm`, cached
as its own build `subtitle:llm`, with a retention check and a per-chunk
fallback — but no `subtitle:llm` build has ever been made, so whether a
local model can put the endings back is unmeasured.

Measured. `python main.py caption-check --limit N` fetches the machine track
for videos whose manual one is already held, runs it through the same
corrector and analyser, and compares both unit sets and sentence counts.

Which track counts is load-bearing: YouTube offers auto captions in 150-odd
languages and all but one are machine translations of the ASR. `de-orig` is
the original transcript; a bare `de` beside a hundred others is a
translation into German. The command takes `de-orig` where it exists, and a
bare `de` only when the video's own audio is German — which correctly
refused the Indonesian and Dutch videos in a sample of ten.

**Thirty videos, twenty-three with an original-language track, and every
one of the twenty-three is worse than its hand-written counterpart:**

```
                        by hand   by machine
  sentences              20,886       28,939
  teachable               5,130        3,554     -31%
  units kept                   —        98.3%, 1.61x each
```

Teachable means i+1 and well-formed, which is what a page shows. Punctuation
is bimodal — two tracks at 0%, the rest between 18% and 56%, nothing between
— so `PUNCTUATED = 0.05` sits in clear air.

Where it does not punctuate, `MergeCorrector` — which finds boundaries by
punctuation — returns one enormous sentence whose vocabulary looks excellent
and which teaches nothing, since no word can be the only unknown in it.
There is no middle: a track punctuates about a third of its lines or none at
all, so `PUNCTUATED = 0.05` separates them.

Where it does punctuate, the material is still **worse than the
hand-written track** — the opposite of what was first recorded here. Raw
sentence counts flatter the machine by half again and the bar takes it all
back, because ASR over-segments: on one video examined closely, median six
words against eight and 34% of sentences under five words against none by
hand.

The vocabulary is genuinely good — 98.7% of the words only the machine found
are in the lexicon, and most misses are real German the lexicon lacks rather
than debris — but vocabulary was never the question. Counting units alone is
what produced two wrong reports here before the teachable column was added.

So where a manual track exists there is no reason to use the machine one.

Counting units alone hides this completely, which is how it was first
measured here and first reported wrongly. The command now prints sentence
counts and the punctuation rate beside the units.

**And it would not close a single gap worth mentioning.** Eight videos the
hunt refused, all carrying a usable German ASR track, against the 347 goals
the study list cannot reach:

```
   21   stranded goals appear in them
    1   is the sole unknown somewhere
    1   in a sentence that passes the quality bar   (`erwachen`)
```

The words are not missing from those videos — twenty-one of them are said.
They are said beside other unknowns, so none becomes teachable. That is the
same thing `study_out_of_reach.txt` already reports in its own words: 288 of
the 347 are "said but never alone", and more video is what that column is
explicitly not waiting for.

So the gate buys material, not reach. Only the 52 never-said goals are ones
video can help with at all, and eight videos produced none of them.

**Where that leaves it.** Auto captions are usable where nothing else exists
— 242 teachable sentences a video against zero — but they are 31% worse than
a hand-written track and they do not unstrand anything. Worth opening if the
aim is a bigger corpus; not worth opening if the aim is the blocked list,
which is what it was reached for. Of ten videos the hunt refused,
eight carry a usable German ASR track and the two that do not are
non-German audio that should be refused. The attempt log holds 43 refusals
in 140 videos met, so this is roughly a quarter more yield a round.

`--corrector llm` was left unrun, deliberately. Its job turned out to be
harder than this entry assumed — segmentation, not endings, is what costs
the 31% — and even a perfect corrector would not move the stranded count,
which is the thing it was reached for. Decided 2026-09-11: not worth the
model hours. The command still exists if the aim ever becomes corpus size. The rest
of the entry stands: keep auto videos in their own build and
`transcript_source='auto'`, so the reader can see which text a machine wrote
twice.

**What opened it (2026-09-12).** The 31% above is a machine track measured
*against the hand-written one for the same video*. Where there is no manual
track, the comparison is against zero, and this entry already said so:
"usable where nothing else exists". lingoniGERMAN is that case — 882 videos,
and not one hand-written German track in any sample taken of it.

So the gate is the whole of the work, and it is three tests in
`ingest/auto_captions.py`, each from something measured rather than
imagined:

- **punctuation ≥ 5%.** `MergeCorrector` finds sentence boundaries by
  punctuation, so a track without any becomes one enormous sentence with
  excellent vocabulary that teaches nothing. Bimodal, as recorded above.
- **German ≥ 60%,** judged over ~200-character windows across the whole
  track. This one is new, and it is the trap this channel sets: a
  German-*teaching* channel explains German in English, and YouTube reports
  `language: de` for those videos anyway. Two of the four cleanly-punctuated
  videos in the first sample were English instruction at 54% and 24% German,
  against 100% for the two that were really German — clear air, like the
  punctuation threshold. Detection has to read the whole track, because
  `get_transcript` reads the first twenty snippets and these videos open
  "Hallo und willkommen" before running twelve minutes in English.
- **≥ 20 lines,** the floor the manual path already had.

Ahead of all three, the track has to be the original transcript: `de-orig`,
or a bare `de` only when the audio is German. A bare `de` beside a hundred
other languages is YouTube *translating* the speech, and six of an even
spread of twenty-four lingoni videos are exactly that — English-audio lessons
whose "German captions" are machine-translated English.

**Sampling, again.** Six videos off the head of the listing said half the
channel was usable. An even spread of twenty-four said one. `sample-channel`
already carries this lesson in its docstring — a listing is newest-first and
a channel's newest uploads are not its typical ones — and it had to be
learned a second time here. `--dry-run` beside `--auto` judges without
writing, and is the way to ask.

**What this does not open.** Two thirds of that spread failed on punctuation
alone while being 100% German with a hundred lines or more. That is
`MergeCorrector` needing punctuation, not the captions being bad, and
`--corrector llm` is the named path to it — still unrun, still deliberately
so, and `LLM_BASE_URL` is unset on this machine.

One thing to know rather than fix: picking *everything* on the Studying
switch mixes machine captions with hand-written ones, because `_builds(ALL)`
means every cached build. That is how `subtitle` and `transcript` have always
mixed under it; the per-video `auto` mark and the switch are the filter.

The caption endpoint throttles separately from the metadata one and harder.
Downloading a track with `requests.get` — anonymous, no cookie jar — drew
HTTP 429 on the forty-seventh video of a survey while yt-dlp's own requests
were still being answered. The download now goes through the same
`YoutubeDL` instance that fetched the metadata, which is what
`transcript_fetcher.py:242` does and for the same reason. A refusal there is
weather: `Throttled` becomes `unfetchable`, which never settles.

### 8. Backfill `channel_id` on the videos that lack it — DONE

Item 6 needs this and cannot start without it, which is why it is its own
entry rather than a clause inside one. 1,117 of 1,382 videos have a null
`channel_id`, and every one of them is German — the non-German rows came
from upstream with theirs already set.

**The command exists; the work is running it.** `backfill-channels` asks per
channel rather than per video: it takes an unattributed video, asks which
channel it belongs to, lists that channel once, and attributes every video
of ours that appears in it. Measured on three channels, that was 183 videos
for six requests. Each channel commits as it lands, so the work left is
always `WHERE channel_id IS NULL` rather than a position in a queue.

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

### 9. Lists built by searching, and a page that can choose between them — DONE

DONE. The counting switch has three positions; the storage
(`vocab/word_lists.py`), the fuzzy search (`vocab/search.py`) and
`--goals-list` are built; `/lists` is the page — search box, tick, name,
remove, forget; and a **Learning** switch on `/`, `/roadmap`, `/blocked` and
`/lists` chooses which list the whole app is aimed at.

That last part was claimed done here before it existed, which is half the
entry's title. It is a viewer per list rather than a list dimension inside
`_scopes`: a `Viewer` already holds everything a list decides — resolved
goals, narrowed corpus, ranking, scopes — so switching is a different viewer
and nothing else needs re-keying. Built on demand, so a list nobody opens
costs nothing, which was the measured objection to putting it in `_scopes`.
`layout` carries `list` beside `src` into every nav link, since dropping
either silently returns the reader to a default and looks like a broken
switch.

No script on it. Everything is a form and a 303, because the state that
matters lives in `word_list` rather than in the page, and a page that
keeps its own would be a second place for a list to be wrong.

It is the only page here that never loads a corpus: the search reads
`unit_counts`, which answers off the materialized view, so it stays
usable on a machine with nothing left — which is how it was built.

The walk is still a command. `--goals-list NAME` aims one at what you
ticked, and the page says so rather than pretending a button could do it
in a request.

The roadmap's aim is a file: `data/study_list.txt`, or `--goals-file PATH`
on the command line only. Wanted: search the vocabulary with a box that
tolerates misspelling, tick words, name the list; then choose on the page
which list the plan chases, and whether the walk may pay two words at once.

Naming is done. A plan's label carries its builds, `:good`,
`:strict`/`:list`, `:goals`, a non-default list's stem, and `:relax` last
(`commands/build_roadmap.py:70-92`); `read_label` strips them in the
reverse order, and `_stored_label` asks for the list this process was
started with. Before that, a relaxed build overwrote the plain one it was
meant to improve on, and a plan aimed at any other list could not be
reached from the page at all.

`data/b1_parsed.txt` now has all four cells built, which is what made the
rest of this measurable. Three things it showed:

  * A second list costs 2.26s of goal resolution, not a corpus reload —
    `goal_units`, `covered_forms` and `priority()` are the whole of what
    differs. But `_scopes` is keyed `(source, counting)`
    (`web/handlers.py:346`), so a list dimension makes every new cell a
    3.66s cold corpus load: two lists by two counting modes by two sources
    is eight cold builds where there are four. A switch that doubles the
    cold paths spends back what dropping `_drop_duplicates` bought. Settle
    that before building it, not after.
  * Where a cell is missing, `_stored_label` falls back to the other
    counting mode by design, so a switch would offer two positions that
    quietly serve the same plan — which is what b1 did before its strict
    cell existed. Either build every cell a list offers, or have the page
    say which of them are real.
  * `_stranded` composes its replay label from the source alone
    (`commands/hunt_videos.py:197`), so a run aimed at any other list
    replays the *default* list's plan. Measured both ways: identical
    results, because the walk after the replay runs to exhaustion under
    `only_goals`, and what a corpus can reach does not depend on the head
    start it was given. Worth correcting for honesty — but nothing moves
    when it is corrected, so do not expect the numbers to.

Then: lists are judgements, so a `word_list` table in `state.sqlite3` with
`GoalList` reading from it as well as from a file. That file holds
judgements and caches now — the corpus left for Postgres — so a search box
cannot read units from beside it. `unit_counts` returns all 46,433 from the
`corpus_unit_count` matview in 59ms, so a trigram index is thirty lines
over a query rather than over a corpus load; `pg_trgm`, which migration
dd0d9cf4b307 declined because nothing issued a fuzzy query, should be
reopened rather than stepped past if that stops being enough. The walk is
minutes and cannot run inside a request; queue it the way `_queue_rescore`
does. i+2 keeps `--relax`'s meaning, only at the wall (weighing pairs
throughout degrades the whole sequence), and the page shows a relaxed
step's `beside` word, which is already stored.

### 10. Cover a saved list in the fewest minutes — DONE as a command

Take a list the reader built and saved (item 9's `word_list`) and choose
the videos: the set with the fewest minutes in which every word on the list
has at least five different sentences where it is the sole unknown. Show
the videos, and under each word its five sentences. Recompute only when a
regenerate button is pressed; until it is, serve what was stored, however
old.

Decided 2026-09-11 over two other readings of the same request. A cover of
*sentences* is nothing to solve: an i+1 sentence has one unknown, so it
covers one word and no other, the sets are disjoint, and the answer is five
a word by `examples.rank`. Letting a sentence count for every list word in
it — nothing unknown *off* the list — gives a solver something to do,
26,053 such sentences over the default list, at the price of serving what
is not i+1 as this project defines it. Videos keep i+1 strict and still
overlap, because one video holds sole-unknown sentences for many words; the
cover is real, and it answers in minutes.

The solver is language-app's `ilp/optimal_set_finder.py`: PuLP over CBC, a
binary per file, cost the file's word count, one constraint per target word
that at least `min_occurrences` chosen files contain it — a word that fewer
files contain is asked for as many as there are, rather than making the
model infeasible; solved at `gapRel=0.08`. It is this problem with `file`
read as `video`: the cost is `video_minutes`, "contains" is "holds a
sentence where the word is the sole unknown", and the constraint counts
sentences rather than videos, so one video may supply all five — cap what
one video may contribute if five from one speaker turns out to be no
lesson. Lift the model, not the module: it reads that project's
`word_occurrences` table, writes its answer to text files under `ilp/`, and
prints as its output. `pulp` is a new dependency, pinned in neither
project; its wheel ships CBC.

The pool is `CorpusIndex.candidates()` — the sole-unknown positions per
unit — grouped by `timing.video_id` as `build-video-roadmap` groups. Count
texts, not positions: 21 of 28,453 repeat. Only the `subtitle` build is
timed; the `transcript` build has no video and cannot be in a cover.
`VideoWalk` is the nearest thing here, the same material walked greedily in
sequence by what each video teaches given the ones before it; this is a
set, not an order, aimed at a list, so it gets its own store beside
`VideoRoadmapStore` rather than a mode of it. Keep the walk's `ENOUGH_LINES`
floor: minimising minutes rewards clips, and a cover of forty ninety-second
videos is not a watching plan.

Measured 2026-09-11 over `corpus(strict=True)`, against a known set of 984
units and the *default* study list — 4,007 units, 3,639 of them not known.
A hand-built list will be tens of words, and none of this carries:

    list words with sole-unknown sentences in videos
      five or more                                        829
      one to four                                       1,243
      none in a video, some in the transcript build       241
      none anywhere                                     1,326
    videos holding any of it — the binaries               850   list words each: median 13, max 229
    greedy five-deep cover, by words a minute             683   videos, 14,319 minutes

The greedy cover is an upper bound, and for this list it is most of the
catalogue: a list this size is not a cover but the whole corpus, priced. No
solver moves the top of that table either — the pool is bounded by the
known set, 984 units, not by the corpus, and the only thing that adds to it
is `fill-gaps`, which today writes one sentence per roadmap step that lacks
one, not five per list word, and writes it to the `generated` build, which
has no video. The words a cover cannot reach are listed on the page, not
dropped: language-app prints a WARNING count and moves on, and a page that
does the same shows a cover that looks complete.

The button is where this departs from every other cache here. A cover is a
snapshot of one known set, and the reader's grows daily, so yesterday's
cover holds sentences that are readable today. `_queue_rescore`'s stamp
carries the known-set version and "a disagreeing stamp means recompute,
never serve". This is asked to serve anyway. So: key the stored cover by
list alone, keep the stamp beside it, and let the page say how old it is
and how many of its sentences are no longer i+1 — stale, never in secret.
Keep the solve off the request thread: queue it as `_queue_rescore` does,
show that it is running, and make a second press a no-op — that queue
dedupes nothing, and two presses are two solves. The solve wants a strict
index for its list, which by item 9's measurement is a cold corpus load per
list; pay it in the worker, once a press, rather than adding a cell to
`_scopes`. And the label has to name
the list and the build, or regenerating under one deletes the other;
660fe47 is what happened the last time a name said less than the settings.

Worth: item 9 lets the reader say what they want to learn; this is the
first answer here that takes the list whole and prices it in minutes.

Built: `roadmap/cover.py` (model, `VideoCoverStore`, and an `audit` that
re-counts the answer without asking the solver), and `python main.py cover
--goals-list NAME`. `pulp` is pinned; its wheel carries CBC. The page is
**not** built, and the measurements below are why.

`gapRel` is 0.0, not the inherited 0.08. That tolerance came from a much
larger problem; here 0.08, 0.02 and 0.0 all return the same 41 videos in a
tenth of a second, so the setting was never binding and would have been one
more number nobody could account for.

**The premise does not hold in this corpus.** This entry rests on videos
overlapping — "one video holds sole-unknown sentences for many words". Over
a twenty-word list and the 141 videos that serve it:

```
  words a video can teach     videos
      1                         120
      2                          18
      3                           3
```

85% serve exactly one word; the mean is 1.17. So the problem is nearly
degenerate — it is close to "pick the cheapest video per word" — and that is
why the solver beats a greedy pick by words-per-minute by only 4-7%:

```
  depth 1   ilp 17 videos  541 min   greedy 20  561 min
  depth 3   ilp 29 videos  920 min   greedy 33  956 min
  depth 5   ilp 41 videos 1180 min   greedy 48 1264 min
```

**And the answer is not yet worth showing.** A real twenty-word list gives
40 videos and 18.6 hours: three words have no timed video at all, seven
cannot be taught five deep, and most chosen videos teach exactly one word.
That is a true answer to the question and a bad deal for a reader, and it
is a fact about the corpus rather than the model — the pool is bounded by
the known set, as this entry already said.

So the page waits on the corpus, not on the code. What would change it is
more sentences per list word, which is `fill-gaps` writing five a word
rather than one a step, or more video. Re-run `cover` on a hand-built list
after either, and if the overlap column above moves, build the page.

**Relaxing i+1 does not rescue it** — asked 2026-09-11, measured over the
same seventeen words:

```
  reading                 overlap  videos  minutes  hours   clean sentences
  i+1                        1.17      40     1119   18.6   100%   mean 0.00
  unknowns on the list       1.18      42     1196   19.9    98%   mean 0.02
  any sentence               1.91      21     1282   21.4    12%   mean 3.24
```

"Clean" is sentences with no unknown word besides the one being taught.

Letting any sentence count doubles the overlap and halves the video count,
and still costs *more* minutes — a shorter list of titles for a longer
watch, where 88% of what is shown carries other unknown words, three on
average. The middle reading, which this entry proposed as the interesting
one, changes nothing at all: with twenty words two list words almost never
share a sentence. It would only pay on a list large enough for co-occurrence,
which is the size at which the cover is the catalogue with a price on it.
There is no list size where relaxing helps.

One thing would flip it. The objective is minutes; if it were *videos* —
"how few things must I watch" — then any-sentence wins outright at 21
against 40. That is a different question and worth its own entry if it is
ever the one being asked.

## Other people

### 11. Letting friends run it

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

### 12. The load is now object building, not querying

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

Which pages actually pay it, from 13: exactly one. `/blocked` needs the
sentences and genuinely walks them. `/roadmap` and `/quiz` never load a
corpus at all — they read a stored plan — and `next_up` and `next_json` load
one only when the plan's stamp has gone stale, which a rebuild fixes rather
than a query does.

That changes what this entry is worth. Interning units and packing them per
sentence would speed up one page and the occasional stale fallback, not five
pages. Worth doing when `/blocked` is the thing in the way, and not before.

### 13. Do the stored-plan pages need an index at all? — DONE, but not there

The guess about which pages pay was wrong. `/roadmap` and `/quiz` never
reach `scope` at all: they read the stored plan through `_planned`, and fall
back to `_walked` only when the stamp is stale.

`scope` has exactly two callers. `_walked` really does walk and needs
everything a `Scope` carries. `_stranded` — the blocked list — wants the
sentences and the ranking and nothing else: it builds a throwaway index of
its own so the walk cannot leave the reader looking like they know words
they have never seen. Asking `scope` for the rows therefore built a
`CorpusIndex`, a `RoadmapBuilder` and an `ExampleIndex`, and dropped all
three.

Fixed as the entry predicted — a narrower accessor, not an optimisation.
`corpus_for` caches the sentences under the same key `scope` uses and
`scope` reads through it, so the pairing hazard the entry raises does not
arise: whichever page asks first, the load is shared.

Measured afterwards, on a quiet machine, CPU time best of three with no
profiler attached:

```
  CorpusIndex     0.59s      built and dropped  (this entry guessed 0.58)
  ExampleIndex    0.17s      built and dropped
  RoadmapBuilder  0.00s      built and dropped
  CorpusIndex     0.59s      its own, and it needs this one
```

So 0.76s of CPU a cold `/blocked`, and nothing at all on the other pages,
which never reached `scope` to begin with. Small against the corpus load
beside it — which is the honest shape of this: the load is the cost, and
entry 12 is where that lives.

### 14. What the 84,849 overlay sentences cost — DONE, they are cheap

Measured, and they cost less than the entry assumed. `corpus_unit` holds
**no** overlay rows at all: all 1,742,479 belong to teachable sentences. So
the overlay is 84,849 rows of text and metadata in `corpus_sentence` and
nothing else — roughly a third of that table's 96 MB, against 260 MB for
`corpus_unit` next to it.

The filter is free as well. Counting every row and counting only the
teachable ones touch the same 7,007 blocks and finish within a few
milliseconds of each other, both sequential scans, so the rows the planner
"walks past" are rows it would walk anyway.

Leave them. A separate table would save perhaps 32 MB of a 356 MB corpus and
buy the transcript panel a join, which is the panel's whole cost.

### 15. `roadmap_example` is 65% repeated text — DONE, and it is not the cost

Re-measured, because this file grew from 63 MB to 271 MB while the quality
floor was being fixed and every roadmap re-walked, which is exactly the kind
of change the entry said to reopen on.

It is now 78% repeated — and that repetition is **19 MB**. All the text in
`roadmap_example` is 25 MB, of which 6 MB is distinct. The other 176 MB of
the file is the `roadmap` rows, the decks' own row overhead, the indexes and
58,299 cards.

So normalising would save 9% of the file and buy a join on every deck read,
against a denormalisation that was measured at 29% faster reads. The
earlier decision stands, and now stands on a number rather than on a ratio
that had drifted. Closed: "it looks duplicated" was never the argument, and
"it is most of what is left" turns out to be false.

What actually grew the file was two 24,000-step plans, each carrying a deck
per step. One of them — `subtitle+transcript:good:goals:b1_parsed`, a walk
with neither narrowing nor `only_goals` — was built here to measure whether
dropping both at once helped. It did not (326 goals out of reach against
218), no switch position names it, and the refresher re-walked it on every
rebuild. Deleted, with a VACUUM: 271 MB to 201 MB.

Worth knowing for next time: a plan nobody reads still costs a full walk on
every refresh. `RoadmapStore` has no way to forget one, so it was deleted by
hand. If experiments like that become normal, it wants a command.

### 16. `--unblock` — DONE, and the gaps are now 9

`--strict` sets `only_goals`, so the walk may never teach a word that is
not itself a goal — a goal with one ordinary word in the way is stranded by
policy rather than by the corpus. `--unblock` lifts that and stores the
result under its own name, since it is a different curriculum.

Measured on `data/b1_parsed.txt`, `subtitle+transcript`, well-formed only,
against 2,016 goals of which 336 were already known:

```
  narrowing  may step off list   goals reached   out of reach
  list             —                  1652            28
  strict           no                 1462           218
  strict           yes                1614            66
  none             yes                1354           326
```

Unblocking closes 152 of the 218. Dropping the narrowing as well is worse
than either — `--goals` alone keeps every duplicate surface form in the
sentences, so more of them carry a second unknown that is only bookkeeping.
Those two were changed together in the first run here, which made the flag
look useless; they have to move one at a time.

What is left is 66, and the three kinds want different things:

```
     4   never said at all           only new video (`hunt --absent-only`)
    24   said, never well-formed     the quality bar, or a written sentence
    38   genuinely deep              more material, or accept them
```

The 24 were the interesting ones: the corpus said them 4-7 times each and
`well_formed` rejected every sentence. The bar was too high, at both ends —
see the band's history in `corpus/quality.py`. The floor took that 24 to 7
and the ceiling took it to 0.

Where b1 stands now, same reading, over a catalogue 99 videos larger:

```
     9   out of reach
     3   never said at all       die Phantasie, das Top, die Unterlagen
     0   refused by the bar
     6   said but never alone
```

Nothing here is blocked by a threshold any more. The three absent ones want
video; the eight want either a sentence that isolates them or acceptance.

### 17. `out-of-reach` reported one reading of four — DONE

Two separate problems with `data/*_out_of_reach.txt`, both committed
(`6e5230b`).

It loads the corpus `list_only=True` with no flag for anything else
(`commands/out_of_reach.py:41`), so the report only ever describes list
counting — while `_stored_label` prefers the *strict* plan. For b1 the
report says 28 and the page serves a plan that strands 218.

And its `said` column counts appearances over the well-formed sentences
only, because `_stranded` filters before counting. The header calls that
"how often the corpus says it", which is not what it is. `die
Arbeitslosigkeit 0` means no well-formed sentence has it; the corpus says
it seven times. The two hide inside one number:

```
  b1, subtitle+transcript, well-formed, list counting — 28 unreached
     4   never said at all           only new video helps
    24   said, never well-formed     the quality bar, or a written sentence
     0   well-formed, never alone
```

`_stranded`'s own comment says a badly-said word belongs with the absent
ones because video can fix it, and that is fair — but it is not the only
remedy for those 24, and the file should let the reader see which of the
two they are looking at. A second column, and a header that says what each
counts.

## Goals

### 18. A goal nothing emitted — DONE, and the answer was a data line

Written three times before it was right. Not `GoalList` failing to split
alternatives (it splits them, and says so). Not six goals (five of the six
are nominalised adjectives the corpus holds under neither spelling, so they
are stranded for want of material, which is what `hunt` is for). One goal:
`gucken, kucken`, registered as a pattern canonical, emitted by nothing,
stranded while the corpus said `gucken` 531 times.

**Why nothing emitted it.** Two mechanisms can produce a comma canonical and
neither applies:

```
  Ich gucke gern Filme.      ->  w:gucken                        lemma only
  Ich gucke mir das an.      ->  P:jdn./etw. (Akk) … angucken    case frame
```

The verb path emits a pattern only where there is a case frame, and a bare
`gucken` has none. The variant path rewrites a lemma that differs from its
canonical's head — `rauskommen` to `herauskommen, rauskommen`, `gerne` to
`gern, gerne` — and `gucken` *is* the head, so there is nothing to rewrite.
`angucken, ankucken` looked like a counter-example and is not: it is emitted
once, against 149 for its case frame.

So the matcher is right and the goal was written in a shape nothing
produces. Fixed as data, in `data/goal_lemmas.txt`, which exists for exactly
this — entries the derived machinery gets wrong, hand-checked one line at a
time.

One code change went with it, because the line would otherwise have been
dead: `units` checked the pattern branch first and `continue`d, so a
correction written for a registered canonical was never consulted.
Corrections now outrank patterns. Verified safe first — none of the 19
existing corrections names a canonical, so nothing else moves.

`gucken` is a goal now, and off the blocked list.

## Material, again

### 19. Take the rest of MrWissen2go, and measure a channel before taking it

Channels differ enormously in whether they hand-caption, and that decides
everything — an auto-captioned video is refused by ingest, so a channel's
worth is its manual-subtitle rate, not its size or its quality.

Measured 2026-09-12, ten videos sampled from each:

```
  MrWissen2go              166 of 197 taken     84%
  MrWissen2go (next 230)   156 of 230 taken     68%
  Dinge Erklärt Kurzgesagt 137 of 162 taken     85%
  musstewissen Deutsch      60 of 106 taken     57%
```

**And do not trust a twelve-video sample.** Kurzgesagt was sampled twice,
before and after the cookie fix, and both said 20-25%; it is 85%. The whole
run is the only measurement that counts, because a sample lands wherever the
channel listing starts — newest-first, and a channel's newest uploads are
not its typical ones. Two sampling rounds nearly cost 137 videos and 10,181
sentences on the strength of a number that was wrong by a factor of four.

MrWissen2go has roughly **490 videos remaining**; at 68-84% that is several
hundred more. Take it in chunks — `add-channel @MrWissen2go --limit N` —
so a throttling burst costs one chunk rather than hours.

**What it bought, which is the reason to continue.** 81 videos hand-picked
or from musstewissen took the study list from 347 goals out of reach to 266.
Fifty-seven of those were "said but never alone" — the column this file has
said all along that more video does not help. It does help; what does not
help is more *bad* video. The earlier measurement that said otherwise used
eight videos found by the hunt's relevance search, which were off-topic.
MrWissen2go's 166 then added 23,089 sentences and 88 roadmap steps, and
their effect on the blocked list is not measured yet.

**Sample before committing.** Ten `extract_info` calls tell you a channel's
manual rate for the price of ten metadata fetches, against hundreds of
wasted ones. There is no command for it; `caption-check` is the nearest
thing and answers a different question.

**A note on what the errors say.** A run against Kurzgesagt reported "Sign
in to confirm you're not a bot" on every video and looked throttled. It was
not: `transcript_fetcher` tries cookieless first, and that attempt really is
bot-checked, but the cookie path behind it works — cookies plus
`js_runtimes` and `remote_components`, all three already configured and
documented in `_scrape_opts`. The videos were skipped because they have no
hand-written subtitles. Read the refusal before believing the error.


**Exhausted, 2026-09-12 — and the 68-84% did not hold.** The channel lists
926 videos; 400 are in the catalogue and the other 526 have no hand-written
German subtitles. Twelve sampled evenly across the whole listing — from the
newest down to the channel's first upload, "Los geht's!" — returned
`manual=[]` every time, and a previous run had already tried all 526 and
failed on all of them, so this is a census with a spot-check, not a sample.

The 68-84% rates were measured on the newest tranches, which is where this
channel writes subtitles. Its back catalogue does not have them. Read the
earlier warning about Kurzgesagt the other way round: a rate measured at the
head of a listing does not describe the tail, and it can be wrong in either
direction.

**Exhausted is not permanent.** The back catalogue has nothing; the channel
still writes subtitles on what it uploads now. Between two listings an hour
apart it gained one video, and that video had a hand-written track. So this
is a channel to re-sample every so often, not one to cross off — and the
right cadence is however often it uploads, not a schedule.

**Use `sample-channel` for the next one.** It lists a channel, splits the
unheld videos into written-off / tried-and-failed / never-tried, and probes
a spread of the never-tried for a manual track. Its first version counted
all 527 unheld MrWissen2go videos as new and estimated 66 usable ones; there
was one. Tried-and-failed is not an opportunity, and the command now says so
separately.

**`--limit` does not chunk what you think.** `_collect` passes it to
`lister.videos(channel, limit)`, so it caps the *listing*, before the
already-have filter. With 400 of the newest already held, `--limit 100`
re-walks videos already in the catalogue and fetches almost nothing. To
chunk for real, dry-run the channel, keep the ids it prints, and split that
file across several `add-videos` runs.

## Goals, again

### 20. Goals blocked by their own word — measured, and too small to build

A reader hit this on the page twice. First `das Gen`, "needs 1 other new
word here: gen", fixed by taking the case markers out of `PLACEHOLDERS`.
Then `der Stock`:

```
der Stock — 26x pattern
Der Stock ist eine Etage in einem Gebäude.
needs 1 other new word here: etage
```

That one is honest — a lesson video defining *Stock* by its synonym, blocked
by the synonym. But looking at all six of its sentences turned up three
separate classes, and none of them is worth what fixing it costs.

**The six sentences for `der Stock`.** Four of six are blocked by an ordinal
(`zweiter` x3, `siebter` x1), not by rare vocabulary. One is not the noun at
all: `Aber dann stock doch gleich die Personalmittel ... auf` is the
separable verb `aufstocken`, lemmatised onto `Stock`. So some of its 26
sightings are a different word.

**Three classes, each measured against both lists.**

```
                        b1_parsed        study_list
  stranded goals              45               127
  self-blocked                 3                 4
  freed outright               2                 2
```

- *Filler.* `äh` blocks 4 sentences and frees exactly one goal outright,
  `die Beschäftigung`. Unconditional, and the only clean one — but the
  sentence it frees opens with the filler, so the prize is one mediocre
  example for a corpus rebuild.
- *Ordinals.* Frees 2, and only because `zwei` is known; `sieben` is not, so
  `siebter` stays blocking. A derivation rule that fires on the cardinal is
  a global change and a rebuild for two goals.
- *Self-blocking.* A goal blocked by its own surface form wearing a second
  lemma: `das Gewissen` by `gewiß` (the noun read as the inflected
  adjective), `inner` by `innerer`, `das Lokal` by `lokale`, `das Teilchen`
  by `teilche` — and `teilche` is not a German word, it is a truncation.

**Why the third one is not a bug.** `covered_forms` exists for exactly this
— one word arriving twice — and its docstring already names these as the
residue it accepts: it reads goals' *written* keys rather than lemmatised
ones, and calls the leftovers "a word counted as a stranger that the list
does in fact reach — the safe direction, since it only ever holds a sentence
back". Catching them needs a parser over the goal list, which that docstring
prices and declines.

**And a stem rule would be worse.** The heuristic that found these also
flagged `der Dolmetscher` "blocked by" `dolmetscherin`, which is a different
word. Pardoning on a shared stem would mark sentences readable that hold a
word you cannot read — the unsafe direction, traded away for seven goals.

**The number that decides it.** All three classes together are about 7 goals
of 172 stranded across both lists, and cost a corpus rebuild plus a matching
rule. `scratchpad`'s own database plan carries a STOP banner over a better
ratio than that. Measured, recorded, not built.

The one thing worth doing cheaply if it ever comes up again: `teilche` and
`gewiß` are analyser artifacts, not vocabulary, and a corrections file for
*analyser output* — the mirror of `data/goal_lemmas.txt`, which corrects
list input — would take them without touching the walk.

**Asked for, 2026-09-12.** A reader hit `das Teilchen` "needs 1 other new
word here: teilche" on the page and asked for it fixed, so the measurement
above is overtaken: it is worth building, because it is being read.

**The shape, decided after looking for a cheaper way twice.** Not the
per-sentence override (`sentence_units_override`) — that is keyed by sentence
text, so it would mean correcting fourteen sentences by hand for one word and
would not generalise. Not `data/lemma_overrides.txt` either: that is keyed by
*surface* and consulted only for tokens tagged as verbs, and widening it to
nouns would apply `muss → müssen` to the noun in `ein Muss`.

What fits is a **lemma-to-lemma** file — `teilche → teilchen` — applied to
analyser output. Keyed on the observed lemma rather than the surface, it is
unambiguous exactly where these cases live: `teilche` is not a German word,
so rewriting it is always right, and no real token loses a reading.

**What it cannot fix, and why that is the honest boundary.** `das Gewissen`
blocked by `gewiß` is not this. The surface *Gewissen* genuinely is both the
noun and an inflected form of the adjective `gewiss`, so which one is meant
is context, not spelling. A lemma rewrite would have to pick one and would be
wrong wherever the adjective was meant. Same for `lokale` and `innerer`. So
this takes `teilche` and leaves the ambiguous three.

**Sequencing.** `analyser_fingerprint` hashes `analyzer.py` and its data
files, so this invalidates every stored plan and needs a full
`build-corpus subtitle`. With an import running that would make
`RoadmapRefresher` rebuild all ten plans after every chunk, so the change
waits for the imports to finish and one rebuild then covers both.

## Deck, and what the corpus still does not know

### 21. Read the sentence with the voice that said it

The deck is read by Piper. It is clear, it is consistent, and it is not
German as anyone speaks it — no elision, no swallowed endings, one speed.
A learner who can follow the deck has learned to follow a synthesiser.

The alignment to do better already exists. `Timing(video_id, start, end)` is
carried on every subtitle sentence, and **8,066 of the 11,398 example
sentences (71%) have one** — the corpus knows which video each came from and
where in it. Cutting the real audio is `ffmpeg -ss start -to end`, which is
the same tool the episodes already use.

What is missing is the audio itself. The corpus stores text and timings, not
media, so this needs the source videos fetched and kept — audio-only would
do, and at ~1 MB a minute for speech that is perhaps 40 GB across the
channels taken so far. `yt-dlp` is already a dependency of the scraper.

**The boundary.** 29% of examples have no timing at all: everything from
`transcript` origin, which was written down rather than aligned, plus every
`generated` sentence, which nobody ever said. So this is a mixed deck or a
smaller one — real speech where it exists and Piper elsewhere, or a deck
restricted to what can be cut, which loses a third of the examples and would
change which sentences the walk may use.

Worth a trial on one channel before 40 GB: cut fifty and listen. Subtitle
timings are routinely a beat off, and a clip that starts mid-word is worse
than a clean synthetic one.

### 22. Grammar as something i+1 can count

A sentence is i+1 when it holds one unknown *word*. It can still hold a
tense, a case or a clause order the reader has never met, and the roadmap
has no idea — `Wenn ich das gewusst hätte, wäre ich gegangen` is i+1 by
vocabulary and is a wall.

This is the deepest change on this list, and it is worth saying why before
anyone starts it. `Unit(kind, key)` is the atom of the whole system: 1.7M
unit rows, the known set, the counting rule, the walk, compounds, aliases.
Adding grammar means every sentence carries constructions as well as words,
every one of them has to be detected at analysis time, and every count in
the project gains an axis. It is not a feature on top of this system; it is
a second system beside it.

**What makes it tractable, if it is done.** spaCy already parses every
sentence and the analyser already throws the parse away after taking lemmas.
Tense, mood, voice and case are in the morphology it has in hand, and clause
type is a dependency-tree question. So the *detection* is mostly free — the
cost is the counting model, not the linguistics.

**The cheap half.** Grammar as a filter rather than a unit: tag each
sentence with the constructions it uses, and let a reader exclude
subjunctive or say "no relative clauses yet". That is a column and a
`WHERE`, needs no change to what i+1 means, and would answer most of what
this is actually for.

### 23. Quality as a number the walk can read

`corpus/quality.py` already scores a sentence — `well_formed`, `variety`,
`score` — and the `:good` builds already use the first as a gate. But it is
a gate: pass or fail, recomputed on every load, and the walk cannot prefer a
good sentence over a merely acceptable one.

Three things follow from storing it per sentence instead.

The walk could **rank** rather than filter, which is what the deck actually
wants: of the sentences that teach `die Geschichte`, show the clearest, not
the first to survive a boolean.

A **reader's** judgement could join the model's. The overrides table already
holds hidden and corrected sentences, so the shape exists; a score is a
third verdict alongside them.

And a **model's** could too, now that one is wired up. The gloss pass just
read 11,398 sentences and refused to gloss 28 of them — that refusal is a
quality signal that was thrown away. `etwas machen` was glossed three ways
because its examples were weak; `von etwas zurücktreten` failed four passes
because one of its sentences is transcribed as *"die Verlet"*, which is not
a word.

**Smallest useful version.** A verdict table beside the other overrides,
holding only what cannot be computed — a reader's mark and the gloss pass's
refusals — read by `roadmap/examples.py` as a term *above* the computed
score, so a sentence known to be bad loses to one merely thought worse. The
computed score stays where it is and keeps being computed; nothing is stored
that a function already answers. No change to i+1, no re-analysis.

### 24. Cache the correction? — measured, and there is nothing to cache

Written first as "store the fetched subtitles in Postgres". They are already
in Postgres. `build-corpus subtitle` reads them through `SubtitleSource`
straight out of the shared server, and the migration named *the tables the
scraper also fills* exists precisely so that the scraper can write where this
project reads. Nothing re-downloads anything on a rebuild, and the premise
of the original entry was wrong.

What a rebuild *does* throw away is the **correction**. `_collect` reads the
raw cues, corrects them, aligns them per video, and only then analyses. The
corrected text is never stored — only its analysed result is — so every
rebuild redoes it from scratch.

For `merge` that is cheap: pure Python, no network, spread over processes.
For `llm` it is not. That corrector sends every chunk to a model, and the
corpus is hundreds of thousands of subtitle lines.

The waste is structural rather than occasional. `analyser_fingerprint`
invalidates every cached build whenever the analyser or its data files
change — which is often, and correctly, since a changed analyser means
different units. But correction happens *before* analysis and has nothing to
do with it. A comment fix in `analyzer.py` currently means re-running every
LLM correction in the corpus to get back to the same corrected text.

**Shape.** Content-addressed rather than keyed by video: hash the input
chunk, store the corrected text against `(hash, corrector, version)`. Then
re-importing a video, re-chunking it, or importing the same line from two
videos all hit the same entry, and a corrector change invalidates by version
exactly as `GLOSS_VERSION` does for the glosses.

**Cost.** A Postgres table and an alembic migration, plus a read-through in
`LLMCorrector`. The rows are the same order of magnitude as
`corpus_sentence`, which the database already holds comfortably.

**Measured, and that is the answer.** `--corrector` defaults to `merge` and
`llm` is opt-in. An LLM-corrected build is filed under `subtitle:llm`
(`build_corpus.py`), and the corpus holds:

```
generated      288
subtitle   397,125
transcript  53,134
```

There is no `subtitle:llm`. The LLM corrector has never produced a stored
build, so a cache for it would cache something nothing runs — and `merge`,
which is what everything here was actually built with, is pure Python
over a process pool with no network in it and nothing worth saving.

So: **not built, on purpose.** Both halves of the original entry dissolved
on inspection — the subtitles are already in Postgres, and the expensive
step it would have protected is one nobody uses. Worth revisiting only if a
`subtitle:llm` build is ever wanted, and then the shape above is the one to
build.

### 25. English sentences in the German corpus — DONE, 12,621 of them

Step 5 of the beginner plan teaches `so` with:

```
or I'm dissatisfied with something, I say so, too.
```

Step 20 teaches `also` with `then you very often also hear "Na?" as an
answer.` Both sit in `corpus_sentence.text` — the German field — with
`origin=transcript`, and both were chosen by the walk as the best available
example. Nothing in the pipeline looks at what language a sentence is in.

The source is not a mystery. The transcripts are bilingual: Easy German
publishes German with an English rendering alongside, and the import takes
lines without asking which side of the page they came from.

**The scale is unmeasured, and a first attempt at measuring it failed
instructively.** A word-list test — two or more English function words and no
German ones — found four sentences in 11,398 and *missed both of the known
cases*, because their English contains `so` and `also`, which are German
words too. Every cheap heuristic has that shape: the two languages share
enough short words that presence tests are nearly useless on one sentence.

**What would actually work.** A real language identifier, run once over the
corpus to size the problem before anything is built on it. `lingua` and
`langdetect` both do this and both are a new dependency; a German
function-word *density* test would be cheaper and worse, but might be enough
to decide whether the count is four or four thousand.

**Where the fix belongs, if there is one.** `corpus/filter.py`, which already
decides what enters the corpus and runs before analysis, and whose rejections
are already counted by reason. A language check is exactly the kind of thing
it exists for — unlike `quality.py`, which ranks survivors and would leave
these sentences in the corpus to be picked when nothing better exists.

**What it is not.** The fragment rule added in this session demotes both
known cases, because both happen to start lowercase. That is luck, not a fix:
a capitalised English sentence would rank as well as any German one.

**Done, and it needed no rebuild.** `lingua` over the whole table found
**12,621 English sentences of 445,547 (2.83%)** in sixty seconds — 5,229 of
them in the teachable corpus the roadmap draws from.

`langdetect` was tried first, as proposed, and rejected on measurement. Over
600 real sentences it flagged seven as not-German and five of those were
plainly German — `Papa, wann können wir Samuel abholen?`, `Oder oder kann das
passieren?` — because it is a port of a library built for documents and this
corpus is single short lines. lingua flagged two, both English, and ran seven
times faster. With the plan as stated — use only the German sentences — that
false-positive rate would have deleted real German from the corpus.

A **column**, not a filter, for the reason the entry above gives: the
sentences stay and the algorithms skip them. `corpus_sentence.language` is
nullable, NULL means nobody has looked, and `load(german_only=True)` — the
default — excludes only what has actually been judged. So a corpus that has
never run `detect-language` behaves exactly as it did, and no rebuild was
needed to adopt this.

Verified from both sides: the teachable corpus loads 309,988 sentences with
the default and 315,217 with `german_only=False`, and the sentence teaching
step 5 is absent from the first and present in the second.

## Judgement

### 26. Where a model's judgement could stand in for a rule — surveyed, not built

Surveyed 2026-09-20 against TypeSafe's Jev (`jev-1.13.0`), read from the
live docs that day. What Jev is, in one paragraph: a hosted model that takes
some state and a set of typed questions and returns answers with
probabilities — a **Noul** is a yes/no with P(yes), a **Choice** picks one of
up to 255 options and gives the distribution, a **Score** places the state on
2–10 described levels. It generates no text. Every question in a request is
evaluated against the same state, independently and in parallel, and the
state is charged once per request. $0.042 per million input tokens, output
free; 64k tokens of context; 1,200 requests a minute. The vendor's own
limitations page says it reads instructions literally, cannot count or do
arithmetic, does not treat its input as hostile, and — the line that matters
most here — the state page says *"Primary training uses English; other
languages have lower accuracy currently."* Nothing below is worth wiring
until that has been measured on German, which is what the last section is
for.

**Can it run without the API? No.** There are no weights, no container and
no offline mode; the docs index has no self-hosting page, `models.md`
documents one endpoint, and the SDK (`typesafe-sdk`, Python ≥ 3.10) is a
thin HTTP client for it. `TYPESAFE_BASE_URL` exists, but it redirects that
client to a proxy or a mock — there is no Jev to put behind it. A key comes
from console.typesafe.ai; the docs state no free tier either way. So using
it means sentences leave this machine, which this project has avoided by
design (`generation/client.py` is "the local model client"; the voices are
local). Said once, here, and not again per item below.

What *can* be had locally is the shape. The endpoint in `.env` already does
guided decoding — `response_format` in `LLMClient.complete` — so a yes/no
question with a two-value enum is one output token, and asked with
`logprobs` that token's probability is a stand-in for a Noul. Three things
are lost: it is not calibrated (a chat model's yes/no logprob is famously
overconfident), questions run one generation at a time rather than in
parallel over one read of the state, and it is seconds rather than
milliseconds. What is kept is that nothing leaves. llama.cpp's server and
vLLM return `logprobs`; whether the current endpoint does is one
`check-model` call. This is the fallback for every item below, and for a
few of them it may simply be the answer.

**What i+1 is not.** The ChatGPT note that prompted this survey leads with
"the best application is your i+1 / sentence-selection system": replace the
hard rule with `good_i_plus_one: probability`. That is the one thing not to
do. i+1 here is a count — `sentence.units - known - {target}` is empty — over
`Unit`, which item 22 already calls the atom of the whole system: 1.7M unit
rows, the known set, the walk, compounds, aliases. It is exact, it is
instant, and the vendor's limitations page says of its own model that
counting is unreliable and "we strongly recommend implementing any
mathematical logic in code." The same goes for the note's probabilistic
known set (`während 0.43`): what the reader knows is a list they edit and a
quiz confirms, and a probability there would change the atom, not decorate
it. And the "grammar feature vector" is item 22's cheap half, which item 22
already says is nearly free from the spaCy parse in hand — a Noul fan-out
(`contains_subordinate_clause`, `contains_konjunktiv_ii`, ...) is the
model-shaped alternative, worth measuring only if the parse-based tags
prove unreliable on subtitle German, which nobody has checked yet.

What a model *can* add is the axis the count has no opinion on: whether the
sentence is worth showing. That axis already has a home — `sentence_verdict`,
built for item 23, read by `roadmap/examples.rank` and the walk's picker
above `quality` — and half of what follows lands there.

**Where a rule is standing in for a judgement.** Ranked by how little text
has to leave and how much a wrong rule currently costs. Every cost below is
an estimate from average sizes (an example sentence averages 62 characters,
call it 20 tokens; a Noul with criteria 60–120 tokens) and is to be replaced
by measuring the first hundred and multiplying.

*1. Which compounds a reader can get from their parts.* `data/compounds.txt`
holds 184 checked lines above the marker and 4,830 guesses below it, drained
one keystroke at a time by `review_compounds.py`, and `vocab/compounds.py`
records that about a third of the guesses are wrong: `hochzeit` splits
perfectly into `hoch` and `zeit` and means wedding. The rule that generated
them — both halves are words the corpus says thirty times — cannot see
meaning, and meaning is the whole question. It is one Noul: *would a learner
who knows `hoch` and `die Zeit`, and nothing else about this word, take
`Hochzeit` to mean what it means?* — with the compound, its parts and one
corpus sentence as state. Route on the probability: above a threshold, above
the marker; below one, out; the band between stays in the keystroke queue,
which is the consistency cookbook's shape and turns 4,830 into however many
the model is unsure of. About 200 tokens each, a million in all: **four
cents, four minutes.** Nothing changes at runtime — the answer is a file.

One thing to fix before measuring it. `review_compounds.py` deletes a line on
`p`, so the file holds 184 kept positives and not one kept negative, and
`git log` recovers nothing: the file was committed once, already reviewed.
That is the mistake `vocab/function_words.py` records — "the word list is
derived and can be rebuilt; the judgements about it cannot" — made again in
the next file over. A `p` should strike the line, not remove it. Until it
does, a calibration set means two hundred fresh hand labels.

*2. Which word a goal key teaches.* `vocab/aliases.heads` parses the study
list's own format — `etw./jdn. (Akk) haben`, `jdm. (Dat) etw. (Akk) geben`,
`gern, gerne`, `die E-Mail` — with `ROLES`, `ARTICLES`, `PREPOSITIONS`, the
`_ROLE` regex, a two-pass filter and a comma split, and its docstrings list
the words it had to be taught one at a time (`das Gen` against `(Gen)`, `der
Dank` against `dank`, 39 verbs left unnamed by one version of the
preposition rule). `commands/hunt_videos._search_terms` then parses the same
keys again with a different slot list, `_SLOTS`, and the two need not agree.
This is the complex parsing the survey was asked about, and it is a Choice
with the answer set generated in code: the candidates are the key's own
tokens, the question is *which of these is the word being taught, or none if
it teaches a phrase*. Roughly 4,100 keys at 150 tokens: **three cents.** The
honest note is that the model is not the point here — the point is that the
answer is written down once, as a third column of `study_list.txt`, and both
parsers go. The local model, or an afternoon, would also do it; Jev would do
it in a minute with a probability beside each row saying which ones to read.

*3. Whether a sentence stands on its own.* `corpus/quality.unbound` asks one
semantic question — does every pronoun in this sentence have its referent
inside it? — and answers it with orthography: `THIRD_PERSON`, `DETERMINER`
with a `LOOKAHEAD` of three for its noun, `FORWARD` and `ES_FRAME` for the
placeholder `es`, `NOT_INFINITIVE` to keep `zu den Gästen` from excusing a
`zu`, `ihr` before a lowercase verb. Each list was added after reading what
the previous one flagged (86 of the first 800 flags were good sentences), and
the next reading will add another. `well_formed` and `score` do the same for
"is this a whole utterance" with `CANNOT_OPEN`, the lowercase-first rule and
the ellipsis; `judge-sentences` does it for "has this a main clause" with the
STTS finite tags and a second parse with the first letter lowercased to
un-mislead the tagger, and stores the result as 21,479 `parser` verdicts;
`filter._repeats` does it for "is this one thing said twice." These are four
rules approximating three Nouls — *complete sentence with a finite verb;
understandable without the lines before it; one utterance, not a repeat or
a cut* — and the answers land where the parser's already do, as a new
`source` in `sentence_verdict`, stored as the raw probability with the
threshold in code so a reweighting never reruns anything. Sizes: the 11,398
sentences the deck shows, **12 cents, ten minutes**; the 61,978 the walk
weighed, **65 cents, an hour**; the 315k teachable corpus, **about $3.30
and four and a half hours** at one sentence per request, less if several
sentences share one state. The rules stay as the no-network path — the
verdict is one more source, not a flag beside them.

*4. Standard German.* `polish-sentences` asks the local model two things in
one call and its docstring says why the second needs a model at all: four
cheap tests for dialect were tried and thrown away. The two halves should be
split, because only one of them can move. The repair is generation and
stays where it is. The `standard` boolean is a Noul — *ordinary standard
German, allowing casual speech and contractions like `hab' ich`* — and it
comes back as a probability instead of a flat 0.5 for all 174 marked
sentences, which lets `Schaun mer mol` and a sentence with one regional word
in it be told apart. A free rider on the standing-on-its-own pass above:
one more question on the same state, **four cents** over the shown deck.

*5. Whether a repair repaired anything.* `corpus/fixes.real_damage` decides
which of the model's 2,047 rewrites are worth showing, and by design it can
only accept punctuation and capitalisation: a repair counts when the letters
are untouched, because that is the only way its rule can tell "Was zum
Teufel" invented from "Verlet" corrected. So a genuine spelling fix — the
mishearing the pass was partly asked for — is refused every time. State is
the pair; the question is a Choice over what the edit did: *restored a
sentence boundary · capitalised an opening · corrected a misspelling or
mojibake · restyled without fixing anything · changed or invented a word ·
paraphrased or truncated*. The first three are shown, the rest are not, and
the last is a signal about the sentence itself. Two thousand pairs, **two
cents.**

*6. The lemma the vote could not settle.* Not per token — `corpus/analyzer.py`
runs at 700 sentences a second across four workers and a network call per
token is the wrong shape, and the two-pass vote already settles the majority.
The residue is the point: a surface whose competing lemma does not reach
`CORRECTION_MARGIN`, the `weiß` case where two readings are both real, a
parser lemma no lexicon knows, and `_proper_nouns` where a word is a name in
some sentences and a word in others. Each is a Choice over candidates the
code already has — the parser's lemma, the table's, the surface, the
override — asked per sentence. Experiment 03 left 5,678 disagreement rows
with their sentences and 200 of them judged; at 200 tokens each the whole
file is **five cents**, and the 200 adjudicated rows are the benchmark.

*7. Whether the matcher's sentence carries the pattern.* `deck/gloss.py`
records that the model, asked to gloss `jemandem etwas geben`, declined on
two of three sentences because they were `es gibt` and a subjunctive — the
matcher put them on the card and the meaning is not there — and that
`etwas machen` came back as three senses that were one. Both are
verifications, not generations, and they sit either side of the gloss call:
before it, a Noul per example — *does this sentence use the pattern as
taught, not a homonymous frame* — so the card is built from sentences that
carry the word; after it, a Noul per pair of senses — *would a bilingual
dictionary print these as separate numbered senses* — to merge what the
model split. The gloss itself stays on the local model. Three questions per
card over the 3,902 beginner steps: **about ten cents.**

*8. Grading a pattern card.* `srs/prompt.py`: "the learner writes their own
sentence and grades it against the examples, because nothing here can judge
free production." A Score with levels written as situations — uses the
pattern with the right cases · right verb, wrong case or preposition · a
different construction · not German — is exactly that judge, and a review
session can afford a round trip per answer. Not a replacement for a rule;
the one place on this list that is a capability the project does not have.

**Where it should not go.** `detect-language` moved to `lingua` on
measurement (two flags in 600 sentences against `langdetect`'s seven, five
of those wrong, seven times faster, local) and swapping a measured-good
library for a hosted call is a regression; the auto-caption gate's German
share is the same question over windows and the same answer. `watchability`,
`difficulty`, `priority`, the SM-2 scheduler and the walk are arithmetic
over facts the corpus already holds. `SubtitleAligner` is a sequence match
and is right. `corpus/vectors.py` measured three embeddings and kept the one
that separates a shared topic from a shared word, locally. And anything that
rewrites text — the corrector, the gloss, the translation, `fill-gaps` —
cannot move, because Jev does not generate strings; what moves is the check
beside each of them.

**Where the answers land, if any of it is built.** In `sentence_verdict`
under a source of their own, as `judge-sentences` and `polish-sentences`
already write theirs, with `model` and a question version stored beside
each row the way `GLOSS_VERSION` is — two models answering the same question
are the same problem `deck/gloss.py` describes. The probability is stored
raw and the threshold lives in code, so a change of policy is a `WHERE`, not
a rerun. The existing rules stay as what runs with no network, which they
are today; nothing here is a `--judge` flag beside them. What is sent is
sentence text, compound words and study list keys — never `state.sqlite3`,
whose reader marks are the one thing that is nobody else's business. The
sentences are not all equally public: Tatoeba and YouTube subtitles are, the
`Easy German Transcripts` folder and the language-app corpus are somebody's
material held here, and whether those may go to a third party is a call for
the owner of the corpus, not for this entry.

**Experiment 04 comes first, and it is cheap.** Before any of this touches
the roadmap, the question is whether Jev's probabilities mean anything on
German, and the labels to ask with already exist: the 200 lemma
disagreements adjudicated in `03-lemmatisers-judged.csv` — the judge column
says `claude-opus-5`, a reasoning model's reading rather than a person's,
which is still the stronger reader by a wide margin — as a Choice benchmark:
agreement with that verdict, and whether the losing option's probability is
actually low; the 174 dialect marks and 166 gloss refusals (not gold — a local
model's opinion — so an agreement figure, not an accuracy); the 21,479
`parser` verdicts (a rule, so where the two disagree is exactly what to
read); and, once `review_compounds.py` keeps its negatives, two hundred
compounds. What the experiment reports is calibration, not a score: of the
items given p ≥ 0.9, how many are right when read; and how wide the
unsure band is, because that width is the number of keystrokes the
compounds pass still costs. All four sets together are under a dollar. If the vendor's
"lower accuracy" on German turns out to mean the band is most of the file,
the survey above collapses to the local `logprobs` fallback, and that is
worth knowing for a dollar rather than after wiring anything.

**Measured 2026-09-20 — what a pattern unit is, and experiment 04 built on
it.** The note that prompted this survey came back with a second one: use the
model to judge which lexical unit a sentence realises, with the pipeline
proposing candidates and the model adjudicating. Checking what the pipeline
proposes turned the question round. `data/final_result.txt` holds 4,096 keys
and no key twice — one blueprint per verb, `stehen` is `jdm. (Dat) stehen` and
nothing else — and `extract_german_logic` hands that blueprint to every
occurrence of the verb. So a pattern unit is the verb wearing one label, and
nothing anywhere has asked whether the sentence carries the label. The count
was never wrong by it: every pattern row co-occurs with its lemma (13,744 of
13,744 for `stehen` and `geben`), and strict counting renames the lemma into
the goal, so i+1 saw one unit either way. What was wrong is everything the
label is read for — the card's title and gloss, the sentences chosen to teach
it, and the "senses" the gloss splits it into: 1,523 of 2,780 glossed patterns
came back with two to six meanings, and `jemandem stehen means to stand
(physically)` is the matcher's collapse, not polysemy. 603,624 pattern rows
over 263,693 sentences and 2,818 patterns; the top 25 are 31% of the rows;
11,066 of the 15,434 roadmap goals are patterns.

Two defects, and they are not the same one.

*The parse-decidable half* — built. `Ich habe nicht bestanden` was
`etw./jdn. (Akk) haben` and `Den Restbetrag können sie später zahlen` was
`etw. (Akk) können`: an auxiliary or a modal in front of another verb, credited
with the verb's own frame. The matcher's `dep_ != "aux"` guard never fired,
because the German parse makes the auxiliary the head and hangs the
participle or infinitive under it as `oc`. `phrase_finder.carries_another_verb`
now refuses a `VA*`/`VM*` token with a verb-tagged `oc` child, and skips it
outright rather than letting it fall through to the catch-all branch, which
looks the lemma up too. Over 10,000 fresh subtitle sentences it refuses 2,122
of 10,903 verb pattern rows (19.5%): `haben` 66%, `können` 94%, `wollen` 77%,
everything else 0 — an estimate from re-deriving the rows by lemma lookup,
the matcher's exact path without its fuzzy fallback. **Rebuilt the same
evening, 13 minutes over 397,125 subtitle sentences:** pattern rows in the
subtitle build went from 523,252 to 474,164, −49,088 or −9.4%, where the
reconstruction had said 10.6% of all rows. `haben` about 40,600 → 14,613,
`können` about 20,600 → 1,148, `wollen` about 7,000 → 1,406; `geben` about
10,900 → 2,073, and `es gibt` 8,975 rows of its own, the two together what
`geben` was. 74,121 distinct units, one more pattern than before. The misses are the tagger's — `gegessen` and `heiraten`
read as nouns, so their auxiliary is kept — and the false side is `sein` with
a clausal predicate (`Das Problem ist, dass …`), a few percent of `sein`. Both
left alone: loosening the test to any `oc` child would refuse `wird grün` and
`war betrunken`, and neither error touches the count.

Which needed a second line. Under list counting a verb's presence came from
its pattern row alone — the bare lemma is not a goal and was dropped — so
refusing the auxiliary row would have made `Ich habe das Buch gelesen`
readable to someone who never learned `haben`. `_unit_rule` now renames
before it drops in list mode too, the way strict has since the deletion bug:
the lemma the list teaches under another name becomes that goal, and a
stranger still goes (`tests/test_aliases.py`). That rename is load-bearing
for the matcher change, not a tidy-up beside it: a sentence whose only
`haben` row was the refused auxiliary now says `haben` as a bare lemma, and
both counting modes reach the goal only because both rename. `fingerprint.py` hashes the
matcher, so this invalidates every stored plan and wants a `build-corpus
subtitle`; not run here, because an import was not the only thing it would
collide with — the ten plans rebuild after it.

*The semantic half* — measured, not built. `experiments/pattern_sense.py`
drew 450 pattern rows from the teachable subtitle build, subtitle only so
nothing of anyone else's leaves the machine if a model is ever asked: 300
uniformly over rows, which is what the corpus suffers, and three from each of
the fifty heaviest patterns, which is what the dictionary suffers. Every row
was read against its sentence and labelled *frame* (the blueprint is
realised), *other* (the same word in another sense or frame), *construction*
(a multiword unit the dictionary lacks) or *unclear*; the sheet was judged
blind and the rule column joined afterwards from a fresh parse, so a label is
a reading of the sentence and not of the tag. Judge `claude-opus-5`, as
experiment 03's was, and for the same reason; a spot-check of fifty by a
person is the next thing owed to it. `04-pattern-sense-judged.csv`, report in
`04-does-the-sentence-carry-the-pattern.md`.

```
                       uniform (300)    panel (150)
  frame                     71%              71%
  other                     19%              20%
  construction              10%               9%
  unclear                    1%               0%
  tagged by the rule         30               12     judge agreed on all 42
  residue carrying frame    79%              78%
```

Per pattern, on the panel, the ones that carried their label in none of three:
`haben`, `können`, `wollen` (the rule's), `geben` (three `es gibt`), `stehen`
(be written, `zu etw. stehen`), `bedeuten` (signify, every time), `glauben`
(`ich glaube, …` — think, not believe someone), `aussehen` (`so aussehen`,
never `nach`), `gehören` (`zu etw. gehören`, and twice `gehört` the participle
of `hören` lemmatised onto it — experiment 03's kind of error, not this one).
Every one of these is on the study list, and each card teaches a sense its
examples do not show.

`es gibt` is the largest single construction — 7 of the 43 named — and the
parse marks it: `es` hangs under `gibt` as `ep`, the expletive, in all seven.
Sixty more `geben` rows read afterwards: fifty were `es gibt`, the mark found
45 of them and none of the ten that were *give*; the five it missed hang
their `es` on a modal (`sollte es … geben`) or write it `'s`. So the pattern
is five parts in six a construction that exists as a candidate nowhere: not
in `phrase_table`, not in the dictionary, not on the list. A learner taught
`jdm. (Dat) etw. (Akk) geben` is credited with it and nothing ever teaches
it. Built, on this branch, the same day: `phrase_finder.expletive_construction`
routes `geben` with an `ep` child `es` — or, under a modal or auxiliary,
with `es` as the carrier's subject, which recovers the five misses — to the
canonical `es gibt`; migration `b31e7c0d9a42` registers the canonical in
`phrase_table`, since a pattern the matcher emits is a unit only when that
table lists it; and the study list carries `es gibt` by hand beside `geben`,
with the note saying why it is not in `final_result.txt` (the fuzzy index
would file it under `es` and hand it to every pronoun in the corpus). It
rides the same rebuild as the auxiliary rule. `stehen` has the same shape
three times over: of its 2,816 rows, 360
carry `auf`, 222 `für`, 135 `zu` — `auf etw. stehen`, `für etw. stehen`, `zu
etw. stehen`, a quarter of the verb between them and none a candidate —
while a dative pronoun, the one thing the label's *to suit someone* needs,
is on 72 rows and half of those are `zur Verfügung stehen` or `ihr` read as
a dative. That is a data decision — a key in `final_result.txt`, a
canonical in `phrase_table`, a line on the list, and a branch in the matcher
that reads `ep` — and it is the first thing worth deciding, ahead of any
model. The other 31 constructions the labels named are in the report's last
section (`vor allem` ×3, `eine Rolle spielen`, `auf jeden/keinen Fall`, `zum
Beispiel`, `ums Leben kommen`, `Platz nehmen` …); that list is what the
note's "candidate generation" would have to produce, and the deck's own gloss
already produced most of it unprompted, as the distinct `means` strings per
pattern in `unit_sense`. A discovery pass has a free first draft there.

One bug found on the way, not fixed: `deck/gloss.run` marks a sentence the
model declined to gloss as `sentence_verdict(text, 'model', 0.0)`, keyed on
the text alone. The documented refusal was `es gibt` under `geben` — a fine
sentence that does not carry that pattern — and the mark now keeps it off
every card, not that one. The refusal is a fact about the pair, and the pair
is what the judgement above is keyed on; when a pair-keyed store exists the
refusal belongs in it, and the 166 `model` verdicts should be reread rather
than trusted as sentence quality.

**What the two model arms are now scored on.** The judged file fixes the
items and the labels; the arms read it and report calibration, exactly as
the paragraph above asks: precision and recall at 0.5 on *frame* against the
rest, then of the items given p ≥ 0.9 how many are *frame*, and how wide the
0.3–0.7 band is. The residue after the rule is the interesting part — 270
rows, 79% frame — because the rule already has the rest. Cost is not the
question: 450 items at about 150 tokens is cents on Jev, and the whole 523k
pattern rows of the subtitle build are about $3.30. Per pattern the answer
also says which policy is available: `stehen` keeps one or two rows in a
hundred, so "drop the row" would leave the card nothing to show, and the
verdict has to *rank* examples first and change units only where the sense
survives in enough sentences to teach.

  * *Jev.* `typesafe-sdk` is not installed and `TYPESAFE_API_KEY` is not set;
    both are the reader's to add. The state is the sentence, its tokens, and
    the candidate as canonical, spoken form (`deck.gloss` has it), token
    indices and the gloss's majority meaning; the question is one Noul per
    row — *do the marked tokens realise this unit in this sense here,
    inflection and separated parts allowed*. Subtitle rows only, as the
    sample already is.
  * *Jev — run, 2026-09-20, 450 rows, 302k input tokens, 139 seconds, about
    a cent.* Precision 91% and recall 90% at 0.5, where the matcher's own
    label is 71% precise; on the 408-row residue after the rule, 92% and
    90%, so the gain is on the semantic half. The tails are clean on this
    sample: every one of the 32 rows given p ≥ 0.9 carries its frame, and
    every one of the 30 given p ≤ 0.1 does not. The band is the cost — 153
    rows between 0.3 and 0.7, a third of the file, which is what a person
    would still read. It separates the verbs the way the labels do: `können`
    at .09/.08/.10, `haben` .13/.05/.21, `gehören` .09/.14/.07, `stehen`
    .24/.40/.06, `glauben`, `bedeuten`, `es gibt` .66/.21/.09. Where its
    German gives out is specific and worth knowing: `darüber sprechen` came
    back .30/.12/.23, all three wrong — the da-compound was not read as
    `über etw.` — and plain nouns sit near .5 (`der Herr` as a title .49,
    .38, .51). One row is the question's fault, not the model's: the
    criteria named `Bescheid wissen` as an example and row 329's sentence
    contains it. Neither arm is told the unit's English — the deck's gloss
    would have said *gehört means heard* for `jdm. (Dat) gehören` — only
    the canonical, its spoken form and a one-line legend for the notation,
    so the German is what was tested. What this licenses: *rank* a
    pattern's sentences by p and build the card from the top, where 32 of
    32 were right; not yet *drop* a row on p alone, where a third of the
    file would be a coin toss. `experiments/pattern_sense.py arm jev`,
    scores in `04-pattern-sense-arm-jev.csv` and the report.
  * *Local — run the same evening, 450 rows, 1,304 seconds beside the
    translate job.* Precision 82% and recall 82% at 0.5 against Jev's 91 and
    90; 71 of 72 rows given p ≥ 0.9 right, but only five rows given p ≤ 0.1
    at all — it will not say a confident no — and a band of 163. On the
    verbs it is mush where Jev was sharp: `können` .35/.49/.64 for three
    modals, `haben` about .45, `glauben` .67/.65, `es gibt` .62/.36/.48;
    `gehören` .11/.20/.35 is the one it separates. Usable on the easy
    nouns, not on the question that matters, and 2.9 seconds a row where
    Jev takes a quarter of one. **Decided: the judge is Jev, over subtitle
    text only; the transcripts are not judged.** The local arm stays as
    what runs with no network, which is what it is.
  * *Local.* Probed the same day: `/v1/chat/completions` refuses `logprobs`
    outright; `/v1/completions` returns them, ignores `response_format`
    silently, and honours llama.cpp's `grammar` (`root ::= " yes" | " no"`)
    with the logprobs reported *before* the grammar — which is the
    distribution wanted. The model wants to `<think>` first, so the chat
    template is rendered by hand with the thinking block closed. And at
    temperature 0 the sampled token was not the argmax of what it reported,
    so the arm reads the distribution and never the text. On the one `es
    gibt` probe it leaned the right way at 0.7, which is the shape of the
    calibration question.

**Separable verbs, asked about the same evening.** Not a case for a model.
Over 5,000 subtitle sentences, 432 carry a separated prefix; the parse
attaches 379 of the 447 prefixes as `svp`, and the matcher has folded those
into the verb all along — `steht … auf` is `aufstehen`, 197 with a
blueprint and 182 without one (`zurücknehmen`, `einwilligen`: no pattern,
rightly). Of the 68 it leaves loose, 62 are the tagger calling an adverb a
prefix (`alles dabei`, `hin und zurück`) and six are real misses with
exactly one dictionary candidate (`mitnehmen`, `anfangen`, `weitergehen`)
— a rule if anything. The defect was on the word side, where nothing had
looked: `corpus/analyzer._units` read the tokens one at a time and emitted
the bare stem and the particle as two units, 350 of the 379 times. Under
strict counting that put `stehen` in front of `aufstehen`, `fangen` (to
catch) in front of `anfangen`, and `willigen`, which is not a word, in
front of `einwilligen` for good. Fixed in `8b489ff`: the unit is prefix
plus stem, the particle yields nothing, the corpus vote still sees the
bare stem, and a stem it repairs is repaired under its prefixes too.
Rebuilt: `fangen` 560 → 96 rows and `anfangen` 619 → 1,077, `kommen`
7,433 → 6,077 and `mitkommen` 41 → 126, `auf` as a unit 17,042 → 15,577;
19,823 particle-units gone from the subtitle build, pattern rows unchanged.

**Decided: B, the goal is the verb (2026-09-20).** Asked as a choice — A,
the card keeps the frame's title and the judge picks examples that match
it; B, the card is the verb, examples are its ordinary uses, and a use a
learner cannot get from the verb (`es gibt`, `auf jdn. stehen`) is a unit
of its own with its own line. B, because the list means the verb and the
frames were an accident of the dictionary. Built so far: `spoken` says the
verb for a case frame (`632f691`), the gloss version is 5 so the deck asks
what `stehen` means rather than what `jemandem stehen` does, and a
construction consumes its words in the analyser — `Es gibt ein Problem`
no longer carries `geben`, which strict counting had been renaming back
into the `geben` goal, so the sentence had stayed a `geben` example with
the pattern row gone. What is left of B is the ranking of examples by a
judge, and that waits on the design below.

**The corpus pass is one request per sentence, not one per pair — asked
for, 2026-09-20, before any run.** State is charged once per request and
every question over it runs in parallel, so the pass that ranks examples
should carry every question the project will want of a sentence: the
plain-word Noul per unit (B's question), the grammar Nouls of item 22, the
standing-alone Nouls of item 3, the standard-German Noul of item 4, and a
discovery Noul for fixed expressions the units do not name. About a
thousand tokens a sentence, 262k teachable subtitle sentences, roughly $11
and three and a half hours at the rate limit, once, stored raw with a
question version. Each group gets its few-hundred-row measurement first,
and nothing runs without a go. The B-question re-score on the 450 is
written (`arm jev plain`) and unrun.

**The questions, decided one by one the same evening.** Quality first;
grammar out — "I don't want grammar that much, I care more about the
quality of the sentences." Six survive:

  * `stands_alone` — *Can the sentence be understood without requiring
    more context?* The reader's own wording; it asks the thing rather
    than listing the ways it fails, and it means the sentence is judged
    alone, so the line before it left the state. Replaces `unbound`.
  * `complete` — *Is the sentence one whole utterance, something someone
    finished saying?* Replaces `well_formed`, the `parser` verdicts of
    `judge-sentences`, and `filter._repeats`.
  * `standard` — *Is it ordinary standard German?* Casual speech and
    contractions count as standard. Replaces the flat 0.5 dialect mark.
  * `well_formed` — *Is it correct German as a native speaker would say
    it?* Names of people, places and brands, numbers, and foreign words
    used as German uses them are taken as given and never count against
    it — asked about and settled: a name cannot be judged for spelling
    from one sentence, and `FREE_TAGS` already says a name costs nothing.
    Replaces nothing; it is the signal the gloss refusal had been standing
    in for, and it says which sentences the repair model should be asked
    about at all.
  * `plain`, one per pattern unit — *the word itself, in any ordinary
    sense or frame, not a fixed expression and not a look-alike?* B's
    question; the 450 labels give it 398 yes and 50 no. Ranks a card's
    examples.
  * `expression` — *does the sentence contain a fixed multiword expression
    a learner needs whole?* A filter, since Jev names nothing: the yes-set
    goes to the local model for "which one", and what comes back a hundred
    times is a candidate unit. The only path to `und zwar` and `na ja`,
    which hang on no pattern unit.
  * `guessable`, one per pattern unit — *could a learner who knows every
    other word work out what this one means from the sentence alone?*
    Added when asked what else was worth asking. `plain` says the sentence
    is the word; this says the sentence teaches it, which is the premise
    of the walk — an i+1 sentence is one whose unknown can be inferred —
    and the ranker has approximated it with length and variety until now.
    Ranks a card's examples beside `plain`.

Declined from the same list: `translation` (is the local model's English
faithful? — 254k unverified lines, every card shows one; left for later)
and `unpleasant` (vulgar or graphic — the hide button does it by hand).

Dropped: `register` (a Choice over conversation / explanation /
specialist / meta — taste, which lives at the channel level and in the
hide button) and `demand` (a Score of grammatical load for ordering a
card's examples — length keeps doing that job). Merging subtitle lines by
Jev — a Choice per cue boundary, code joins the runs, about a dollar —
was asked about and declined: the merging logic stays as it is.

State per request: `sentence`, `tokens`, `units` with spoken form,
canonical and token indices, `notation`. Eight hundred to a thousand
input tokens a sentence; the 262k teachable subtitle sentences come to
roughly $8–11 and four hours at the rate limit, once. Before it: `plain`
on the 450 rows, and the four quality questions on a slice of three
hundred against what the rules already say — each with a go.

**Calibrated, the same night, each with a go.** Three runs, four cents.

  * `plain` on the 448 labelled rows (400 the word itself, 48 not):
    precision 95% and recall 93% at 0.5, 92 of 92 rows at p ≥ 0.9 right —
    but the base rate is 89% and it gives only two rows p ≤ 0.1, so it is a
    ranking, not a threshold. Half the constructions sit at 0.5–0.8 (`zum
    Beispiel`, `vielen Dank`, `nach Hause`, `Krieg führen`), below the 92
    a card would draw from. All seven `es gibt` rows came back as `geben`
    used as itself, which is moot — those rows are `es gibt` units now.
  * `guessable` on 100 rows I labelled (84 yes, 16 no): not calibrated.
    Yes rows sit at a median of .68, no rows at .60, everything within
    .2–.9; the four lowest are all no (`Bundestag` twice, `die Partie`,
    the garbled `Nub`), so the ordering carries something and the number
    does not. Open: re-ask it as a Score — *defines the word / hints at it
    / says nothing* — or drop it and let `plain` and length rank.
  * The four sentence questions on a 582-sentence slice built from what
    the rules flagged, plus a control they passed
    (`experiments/corpus_pass.py`, `05-are-the-quality-questions-
    calibrated.md`). The control behaves — `complete` .96, `standard`
    .91, `well_formed` .88, `stands_alone` .80 median — and every
    disagreement read was the rule's error, not the judge's. The parser's
    no-finite-verb flag: 73 of 100 are complete replies (`Vielen Dank für
    das Hintergrundgespräch.`, `Nein, nur noch 10 Minuten.`), which puts
    something like 12,000 good sentences at the bottom of the ranker
    today. `unbound`: 58 of 100 stand alone (`Habt ihr eine Pizza
    bestellt?`). The dialect marks: 85 of 104 are standard German — the
    local model called `'ne` and `gibt's` dialect. The refusals split
    exactly as the survey guessed: `Schein nicht so laut, sonst wächst du
    Mama.` at .08, `Ich bin mir nicht sicher, ob ich bestanden habe.` at
    .97. Names taken as given, 43 of 50; the two doubted are garbled. And
    the control's lowest on `complete` — `Die Frauenärztin Michaela
    Reichert, die ich zu diesem Thema traf.` at .21 — is a fragment every
    rule passed. The four stand as written, version 1.
  * `level` (a Choice over A1–C1, the expected level scaled to 0–1) joined
    the set when a per-sentence difficulty number was asked for; a video's
    difficulty is the distribution of its sentences' levels, in code. Not
    yet calibrated: there is nothing to score it against but a reader.

The questions live in `corpus/questions.py`, as data, with a version the
answers will be stored beside; the calibration and the pass read one file.

**The pass is built (`0c76d4b`), unrun.** `ask-sentences`: one request
per teachable subtitle sentence — 214,431 of them, 17,688 shown on a
card first, then 75,021 the walk weighed, then the rest — carrying all
eight questions; answers raw in `sentence_answer`
(`corpus/answers.py`), keyed by text, unit, question, version and model;
resumable; `--dry-run` prints the first request and sends nothing;
`--limit 500` is the trial that says what a sentence really costs.
`Application.judged` loads one model's answers and `rank` multiplies
them into the verdict term — worth showing at all (the four quality
answers) times worth showing for this word (`plain`, scaled by
`guessable` but never gated by it) — so the walk, the pages and the
stored decks order alike, and an empty store orders as today. The
gloss's refusal is a pair-keyed answer now, and the 166 sentence-wide
marks it used to leave are gone. `judge_model` is pinned to `jev-1.13.0`,
the version calibrated, so `jev-latest` moving cannot silently change
what is read back.

**Run, 2026-09-21, on the beginner plan.** The account held $4.80, so
the pass met a budget rather than the corpus: one plan's candidates
(`--plan beginner` — the sentences its 3,902 steps had stored, 44,667 of
them subtitle) and every question but `guessable` (`--skip guessable`,
the one that ranked weakest). 44,326 sentences after the 500-sentence
trial, 0 failed, 73.1M input tokens, **$3.07**, 66,600 sentences an hour
at six in flight — 1,664 tokens a sentence against 2,022 with
`guessable`. What the answers say about sentences that cards show today:
`complete` .95 median, `well_formed` .83, `standard` .86, `stands_alone`
.67 — the judge doubts that a quarter of card-shown sentences stand alone
— and the quality product's median is .38, since four probabilities
multiplied compress. `level`: A1 20 · A2 109 · B1 286 · B2 81 · C1 4 of
the first 500; a video's mean already orders *Easy German Podcast* (.35)
below *Barbarossa* (.55). Two things the run found before it was over:

  * `die meisten` credited with `der Meister`, 730 times — the parser tags
    `meisten` as a pronoun with lemma `meister`, the fuzzy fallback scores
    identical letters 1.00, and the trust gate accepted a perfect score.
    `plain` put `der Meister` at .10 in `Zunächst lebten die meisten
    Deutschen als Bauern auf dem Land.` The same door let `leid` reach `das
    Leid`, `mal` `das Mal`, `pass auf` `der Pass`, `klasse` `die Klasse`:
    about 1,650 rows. Fixed in `562de90` — an article-noun entry needs a
    noun-tagged token in the match — and rebuilt.
  * An unjudged sentence scored 1.0, the best. The walk picks a card's
    candidates with `rank` from every sentence that says the word, and the
    pass judges only the candidates it finds stored; at 1.0 the unjudged
    thousands would have won every pick and the answers would have ordered
    nothing. Unjudged now scores the median of the judged (`9703374`) —
    good stays in, bad drops out, what replaces it is judged next run.

And the deck is eight (`d3de42b`), down from twenty-four: that depth was
what it took to find three good sentences by characters alone, and with
the judge in the pick the deck is the eight best the word has. Six is the
floor (three shown, spares for `spread`); eight leaves the reading page
something past the card. Half the judging cost of twenty-four per plan.

**Closed out, 2026-09-21, 02:50.** Five walks and five rebuilds after the
pass, because each walk showed something the answers had made visible:

  * an unjudged sentence had scored 1.0 and would have won every pick
    (`9703374`); `gibt's` was one token with a nonsense lemma and no
    construction (`94cf223`), and the expletive left `es` and `’s` standing
    as units (`92b8bd3`);
  * `Why did I stand in the pillory?` was on the `stehen` card because the
    four rebuilds had wiped every `language` mark — `build-corpus`
    reinserted the rows and never carried the column; `save` keeps it now
    and `detect-language` re-marked 12,640 in 76 seconds;
  * `Und es gefällt mir …` taught `der Fall`, because the corpus vote's
    correction for the surface `fällen` (the noun's plural, lowercased)
    was applied to every unit keyed `fällen`, the parser's own lemma for
    `gefällt` included — 157 sentences; a correction now touches only a
    unit whose surface is its key;
  * and, from an audit of every write the code makes, two more of the
    language-wipe shape: `judge-sentences --limit` replaced the whole
    `parser` source with its sample, and `polish-sentences`, which resumes,
    left only its last batch's dialect marks — 174 of thousands — every
    run; `build-study-list` wrote over the file's hand lines and its
    header invited the rebuild. All three guarded (`0f33121`).

Ledger: $3.14 of $4.80 — 46,032 subtitle sentences judged, every
candidate of the beginner plan — and the plan stands at 3,883 steps,
decks of eight, 27,121 sentences, 385 of them judged in the last cents.
Backups in `dump/`: the state database before and after, Postgres before.
Still stale: the four other stored plans (built 2026-09-14, old units,
decks of 24, unjudged) and the running `serve`, which started before any
of this and needs restarting to see it. The gloss version is 5, so
`gloss-deck` will re-ask the cards' meanings about the verb.

**What this does not settle.** The list writes `stehen<TAB>jdm. (Dat)
stehen` and means the verb; the frame came from the dictionary. Once rows
are judged, the goal `jdm. (Dat) stehen` would teach *to suit someone* from
the few sentences that carry it, which is not what line 99 asked for. Whether
a verb's goal is the verb or the frame is item 2 of the survey above, and the
per-pattern table is the first measurement of what each answer costs. Experiment
04 is this benchmark; the lemma disagreements, dialect marks and compounds
listed above stay as the second set, for the calibration question itself.
