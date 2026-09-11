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

### 6. Subscribe to channels, or pick genres, and prefer their videos

The reels and the video roadmap rank every video in the catalogue by what it
teaches and how well it plays. Nothing says whose videos the reader would
actually sit through, and a channel they like is a stronger reason to watch
than a tenth of a sentence a minute.

The blocker was data, and it is gone. All 1,483 videos now carry a
`channel_id` — a foreign key to `channel`, not the YouTube string — across
280 named channels (item 8). `video.category` is still no substitute for a
genre: 1,155 of 1,382 are YouTube's "Education".

The catalogue is lopsided, which matters for what a preference is worth:

```
  Like Germans                 692
  UNED                         246
  Deutsch lernen mit der DW     28
  Dinge Erklärt – Kurzgesagt    25
  ... 276 more channels
```

Two channels are 63% of it. Preferring one of those changes little; the
weight only has teeth on the long tail, and a preference for a channel with
twelve videos will run out fast — which is the argument for a weight and a
tie-break rather than a filter, already made below.

Once the column is filled: a subscription is a reader's judgement, so it
lives in `state.sqlite3` beside `known_units`, not in `channel.active`,
which is the scraper's flag. Apply it as a weight in `_score_video` and a
tie-break in `VideoWalk.build`, never as a filter — the walk stops when
nothing left teaches, and a walk over one channel is a different curriculum,
not a preferred one. Say what the preference costs in sentences taught.

### 7. Auto-generated captions — MEASURED, gate not opened

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

### 18. A goal written as alternatives can never be reached

`data/study_list.txt` writes alternatives with a comma — `gucken, kucken`,
`der Beamte, die Beamte` — and `GoalList.entries` keeps the line whole, so
the goal's unit key is the entire string. No corpus unit is ever equal to
it, so the goal is stranded whatever the corpus holds.

It is not hypothetical. Of the 52 study-list goals reported as never said,
six are comma pairs, and the corpus already says half of one of them:

```
  gucken, kucken          corpus has gucken, does not have kucken
  der Beamte, die Beamte  neither half
  ... four more
```

So `gucken` is taught by the corpus today and the goal sits on the blocked
list regardless, and `hunt --absent-only` will chase it forever.

`commands/hunt_videos._search_terms` already splits on the comma — its
docstring records the round that went looking for `kucken`, which nobody
writes, while `gucken` was there all along. That fixed what the hunt
*searches for* and not what the goal *matches*, which is the half that
decides whether it is ever satisfied.

The fix is in `GoalList.units`: an entry naming alternatives should resolve
to a unit per alternative, satisfied by any of them. That changes the goal
count and every plan built from it, so it wants the same treatment as any
analyser change — measure how many goals move first, since a list that
suddenly reaches six more is a list whose numbers no longer compare with
yesterday's.

