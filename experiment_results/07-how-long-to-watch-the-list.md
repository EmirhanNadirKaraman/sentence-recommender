# How long does it take to watch your way through the study list?

Numbers from `experiments/video_order.py`, rerun on 2026-09-25 against a
corpus rebuilt after the lemma fixes, and against my own known words as they
stood then. **Everything moved, and in one direction**: the i+1 walk at K=1
went from 194.4 hours to 202.4, at K=5 from 599.6 to 627.8, and the words to
learn fell from 3,660 to 3,622. That is the fixes working rather than
failing -- merging invented lemmas into the real ones removed the cheap false
ways in, because `atomen` and `atom` were never two words. The old figures
were flattered by damage; these are the honest ones. `07-video-order.csv` is one row per run; `07-plan-*.csv` and
`07-cover-*.csv` are the orders themselves, one row per viewing, with a
YouTube link on every line; `07-words-*.csv` is the same run priced per word.
`07-long-tail-words.csv` is the side question about single-source words. The
`-floor10` files are the whole suite again over a larger shelf; see **The
floor under an episode** below.

## What this tests

A roadmap orders words. This orders *videos*: watch them in some order and
each is worth more than it would have been, because the ones before it taught
the words it needed. The question is how few hours that can take.

Three knobs, and the shelf is 1,500 videos plus 513 Easy German episodes.
Episodes have no running time recorded, so theirs is estimated from their word
count at a measured speaking rate — the softest number here, ±15%.

* **K** — how many times a word must be met before it counts as learned. K=1
  is what `VideoWalk` assumes; the SRS asks for 5.
* **gate** — whether an encounter must be an i+1 sentence (the word the only
  unknown in it) or merely an occurrence.
* **stepping stones** — whether a word off the study list may be learned when
  that makes a word on it cheaper.

Rewatching is allowed throughout: a video seen once has fresh i+1 sentences to
give once its other words have landed elsewhere.

## What it costs

3,660 words to learn. K=0 is the minimum cover — no order, no rewatching, a
lower bound rather than a plan.

| gate | K | hours | videos | viewings | words met |
|---|---|---|---|---|---|
| i+1 | 0 | 127.1 | 329 | — | 3,558 |
| i+1 | 1 | 202.4 | 677 | 700 | 3,556 |
| i+1 | 5 | 627.8 | 1,411 | 2,108 | 3,404 |
| any | 0 | 53.5 | 172 | — | 3,610 |
| any | 1 | 86.6 | 340 | 340 | 3,610 |
| any | 5 | 270.0 | 862 | 862 | 3,610 |
| i+1 + stepping stones | 1 | **162.7** | 536 | 601 | **3,599** |
| i+1 + stepping stones | 5 | 861.9 †‡ | 1,484 | 2,689 | 3,497 |

† Not comparable with the `i+1` K=5 row above it. The held walk finishes a
word once it has had every encounter the corpus can give — `min(K, chances)` —
and the stepping-stone walk insists on five from every word, 18,300 required
encounters against 16,847. Same K, different question. See below.

‡ And the only row here still priced with the English half of the bilingual
transcripts counted in (see the last section). `sweep` does not walk it — it
is ninety minutes on its own — so it was left rather than quietly refreshed
beside rows that were.

Three things fall out.

**K is not linear.** Five encounters cost 3.1× one, not 5×, because a video
seen for one word is giving encounters to forty others at the same time. But
under the i+1 gate it also costs *coverage*: 137 words that K=1 reaches are
out of reach at K=5, because a word stays unknown until its fifth encounter
and goes on blocking every sentence it appears in until then. Insisting on
five is not the same plan five times; it is a harder problem.

**The gate is worth more than K.** Dropping from i+1 to counting any
occurrence more than halves the time at every K. That is not a free lunch —
an encounter in a sentence you cannot read is worth less than one you can —
but it bounds what the i+1 rule is buying: at K=1, 109 hours.

**Stepping stones pay for themselves at K=1, and only at K=1.** Allowing
off-list words costs 23 hours *less* than refusing them (170.9 against 194.4)
and reaches 42 more words. At K=5 it reads as costing 265 hours *more* (861.9
against 597.3), but **those two runs are not solving the same problem** and the
difference should not be quoted as a result. `walk` asks for `min(K, chances)`
encounters, so a word the corpus says three times is finished at three;
`open_walk` asks for five from everyone. That is 18,300 required encounters
against 16,847, and the open walk spends 602 of its 862 hours on the 559 words
that have fewer than five i+1 sentences to give — words the held walk never
chases. Any honest comparison at K=5 needs the same `need` on both sides, and
this suite does not have it.

What can be said from the open K=5 plan alone: the fallback that buys an
unlock fires 4 times at K=1, costing 2.5 hours, and 847 times at K=5, costing
324.2 hours — 38% of that plan. A goal stays unknown until its Kth encounter
and blocks every sentence it appears in until then, so at K=5 the walk runs
out of direct teaching constantly and keeps paying for indirect. The
mechanism is the one in the question that prompted this: `sowie` held to the
list is charged 102 minutes, its only unblocked sentence sitting inside a
204-minute cut of *JFK*. Allowed off-list words it is charged 10.8 minutes,
learned from *3 Erfindungen, die die Welt veränderten* — and the plan never
makes a detour for it. The word that had been blocking it was picked up
incidentally hours earlier, which is the more interesting half of the result:
of the 15,680 off-list words the walk learns, all but a handful arrive free,
as a side effect of watching German at all. Only 4 videos are taken purely to
unlock others, and they come near the end, once the free supply runs out.

## What each word costs

`07-words-*.csv`, one file per run, dearest first. A viewing's minutes are
split across the words it gave encounters to, in proportion to how many it
gave each, so the charges add up to the hours the plan really takes. A
stepping stone teaches no goal at all, so its minutes are split across the
goals it opens.

| column | meaning |
|---|---|
| `minutes_charged`, `hours_charged` | that word's share of the plan |
| `sole_minutes` | minutes of viewings where it was the *only* word gaining |
| `encounters` / `needed` | how far it got toward K |
| `finish_hour` | hours into the plan when its Kth encounter landed |
| `longest_minutes`, `longest_is`, `where` | the longest thing watched for it |
| `sources` | things on the shelf that could ever teach it under this gate |
| `teaching_sentences` / `any_sentences` | i+1 sentences / lines saying it at all |

These are shares, not leave-one-out costs. Dropping a word may save less than
its charge, because the video was worth watching anyway, or more, because it
was holding others back. It is right at the extremes, which is where the
question gets asked.

## Where the hours are

| run | unmet | never said | one source | top 100 words | total |
|---|---|---|---|---|---|
| i+1 K=1 | 63 | 12 | 123 | 76.4 h (40%) | 193.0 h |
| i+1 K=5 | 200 | 12 | 117 | 107.6 h (18%) | 597.3 h |
| any K=1 | 12 | 12 | 22 | 45.1 h (54%) | 83.8 h |
| any K=5 | 12 | 12 | 22 | 103.8 h (41%) | 252.5 h |
| stepping K=1 | 23 | 12 | 15 | 65.5 h (41%) | 161.0 h |
| stepping K=5 † | 163 | 12 | 0 | 135.4 h (16%) | 861.9 h |
| i+1 cover | 61 | 12 | 125 | 36.0 h (28%) | 130.2 h |
| any cover | 12 | 12 | 22 | 17.2 h (31%) | 55.0 h |

The plan is not expensive because 3,660 words each cost a little. In the i+1
K=1 walk the dearest 100 words carry 40% of the hours, and 123 words with
exactly one source on the whole shelf carry 60 of the 193 hours between them —
3% of the list for 31% of the time. Every one of them is a feature film
watched almost entirely for a single word:

| word | charged | lines | watched |
|---|---|---|---|
| der Architekt | 113.3 min | 13 | *Deutsch lernen (B1): Ganzer Film* |
| das Wiedersehen | 113.1 min | 1 | *Lerne Deutsch durch Geschichten* |
| das Glied | 110.5 min | 3 | *25 km/h (2018)* |
| die Ausführung | 106.6 min | 10 | *Du scrollst NICHT aus Langeweile* |
| gewiss | 103.9 min | 6 | *Sahara – Wüste des Todes (1995)* |
| der Engel · sowie | 102.0 min each | 12 · 74 | *JFK – Tatort Dallas*, 204 min, split two ways |

This is the answer to what the corpus should be expanded with. A shorter video
carrying any one of these words removes most of a film from the plan. Five
words sit in the dearest 150 of six of the seven runs, so they are worth
hunting whatever the rule turns out to be: `die Galerie`, `der Rock`,
`an jdm./etw. (Dat) vorübergehen`, `das Bad`, `jdn./etw. (Akk) vernehmen`.

The unmet words are a different hunt, and the first thing to say about them
is that **none of them needs a new video**. Twelve are never said anywhere on
the shelf — `das Geschäftsjahr`, `das Top`, `der Bube`, `detaillieren`,
`die Anleihe`, `die Konjunktur`, `die Realisierung`, `die Zielsetzung`,
`etw. (Akk) murmeln`, `fotografisch`, `sogleich`, `touristisch` — but all
twelve are said in the corpus, between one and seven times each. They are in
material the shelf throws away, and so are extra lines for every one of the
other 51:

| where the unreached words' lines actually are | lines |
|---|---|
| on the shelf, blocked by a second unknown | 219 |
| in a transcript file the 40-line floor dropped | 161 |
| in a video under the 40-line floor | 67 |

The 40-line floor drops 886 of the 1,399 transcript files, which sounds like
the shelf throwing away half of Easy German. It is not, and the reason is
worth writing down, because the first reading of this was wrong.

The join itself is sound: **not one line is lost to a text mismatch.** Every
line missing from the shelf is missing because its file kept fewer than 40
usable ones. Only 119 of the 886 are genuinely short files. The other 767 lose
their lines earlier, and a street interview shows why — *EG 452 –
Superstitions* has 338 lines and the shelf keeps 37:

| lines | why |
|---|---|
| 239 | never reached the corpus: English translation lines (`Are you superstitious? - No.`) and one-word answers (`Manchmal.`) |
| 32 | interrupted speech (`Okay. - Aber nicht, weil ich...`) |
| 30 | two speakers on one line (`Seid ihr abergläubisch? - Nein.`) |

That is the interview format, not a bug: alternating German and English, short
answers, two voices a line. Across the 365 dropped files with 80+ lines, a
median 62% of lines reach the corpus and 27% survive `well_formed`. Lowering
the floor would mostly buy back material that is not a sentence to learn from.

So this is not the cheap win it first looked like. What it does buy is narrow
and real: 228 of the lines carrying words the walk never reaches sit in files
and videos the floor discards, and those words have no other source at all.

The 51 that are said but never teachable — `geradezu` 17 times, `das Kunstwerk`
16 — carry a second unknown on every line. A shorter video will not fix those;
a stepping stone will, and does: the open walk leaves 23 unmet where the held
walk leaves 63.

## The floor under an episode

The section above says the 40-line floor is mostly doing its job. That is an
argument, and the suite is cheap enough to run instead of arguing. Lowering
the floor for *episodes only* — videos keep theirs at 40 — takes the shelf
from 513 episodes to 1,338, and from 584 hours to 715. The 1,500 videos are
untouched, and so is `target`: reachability is computed over the corpus, not
over what is watchable, so both shelves are compared word for word.

| run | floor 40 | floor 10 | change |
|---|---|---|---|
| i+1 K=0 | 130.2 h · 3,599 | 126.4 h · 3,602 | **−3.8** |
| i+1 K=1 | 194.4 h · 3,597 | 187.4 h · 3,600 | **−7.0** |
| i+1 K=5 | 599.6 h · 3,460 | 600.6 h · 3,475 | +1.0 |
| any K=0 | 55.0 h · 3,648 | 53.2 h · 3,649 | **−1.8** |
| any K=1 | 83.8 h · 3,648 | 78.6 h · 3,649 | **−5.2** |
| any K=5 | 252.1 h · 3,648 | 257.1 h · 3,649 | +5.0 |
| stepping K=1 | 170.9 h · 3,639 | 154.5 h · 3,639 | **−16.4** |

**Every K=1 run gets cheaper and every K=5 run gets dearer**, and coverage
improves in all seven. The gain at K=1 is what it looked like it would be: the
plan trades long films for short episodes. 80 episodes the old shelf could not
offer enter the K=1 plan — 7.9 hours between them, median 4.3 minutes — and
117 things leave, 26.6 hours of them.

Twenty words are taught, at floor 10, by an episode the old shelf could not
offer. These are the displacements, and they are the only per-word rows that
mean what they look like:

| word | was | now | taught instead by |
|---|---|---|---|
| die Malerei | 80.9 min | 7.2 | *EG 132 – Im Erongo Gebirge* |
| jdn./etw. (Akk) vernehmen | 43.7 min | 6.0 | *EG 355 – German only* |
| sanft | 23.1 min | 2.5 | *SEG 32 – German Idioms in real life* |
| jdm. (Dat) winken | 16.2 min | 0.4 | *SEG 117 – How to name Body Parts* |
| die Jacke | 15.0 min | 0.5 | *SEG 170 – German only* |

The larger-looking drops are not displacements at all, and this is the trap in
reading two plans' charges against each other. `das Wiedersehen` falls from
113.1 minutes to 0.5, but it is the *same* film both times: at floor 40 it was
watched twice, once for that word alone, and at floor 10 once. `die
Schauspielerin` falls from 88.8 to 1.5 with its film watched exactly once in
both plans — nothing was saved on it at all, the film simply teaches more words
now, so its minutes divide further. Repeat viewings across the whole plan
barely move, 39 to 38. **A per-word charge is a share of one plan, so comparing
shares across two plans mixes real displacement with re-attribution.** The
aggregate −8.0 hours is real; a single word's delta is not evidence on its own.

Three words become reachable that were not: `der Komponist`,
`die Tageszeitung` and `touristisch` — the last one from the twelve listed
above as having no line on the shelf at all.

The K=5 reversal comes with a caveat and a guess. The caveat: `need` is
`min(K, chances)`, and a bigger shelf gives some words more chances, so 57
words are asked for more encounters at floor 10 than at floor 40 — 16,913
required against 16,847. That is 0.4% more work for 1.2% more time, so the
drift is real but too small to be the whole story, and unlike the open-walk
comparison it does not invalidate the row.

The guess, which this suite does not test: the walk ranks by encounters per
minute, and a four-minute episode with three encounters beats a forty-minute
video with twenty-five. At K=1 that is simply correct, since every encounter
finishes a word. At K=5 a word needs five *distinct texts*, which a short
episode rarely holds, so the walk may be taking the episode, banking one
encounter of five, and still needing the long video afterwards. The viewing
counts are consistent with it — K=1 goes from 635 viewings to 665, K=5 from
1,970 to 2,115 — but consistent is not measured. Settling it means rerunning
floor-10 K=5 with `need` pinned to the floor-40 supply.

So the floor is worth lowering for the plan that is actually being followed,
which is K=1, and the K=5 cost is a reason to fix the score rather than to
keep the floor. Nothing in the app was changed: `episode_floor` is a parameter
of `shelf()`, defaulting to 40, and these runs write their own `-floor10`
files beside the originals.

## Does dropping the machine-made channels cost anything?

A channel marked machine-made already loses its sentences from every card,
deck and plan in the app. What it costs the *schedule* had never been
measured, and the honest way to measure it is to run the suite twice over
shelves that differ only in that. Five channels are marked, which takes the
shelf from 1,500 videos to 1,484 and from 567 hours to 560.

| run | machine kept | machine dropped | change |
|---|---|---|---|
| i+1 K=1, episodes 40+ | 194.4 h · 3,597 | 190.9 h · 3,596 | −3.5 |
| i+1 K=1, episodes 10+ | 187.4 h · 3,600 | 188.9 h · 3,599 | **+1.5** |
| i+1 K=5, episodes 40+ | 599.6 h · 3,460 | 593.4 h · 3,456 | −6.2 |
| any K=1, episodes 40+ | 83.8 h · 3,648 | 84.1 h · 3,648 | +0.3 |
| stepping K=1, episodes 40+ | 170.9 h · 3,639 | 161.2 h · 3,637 | −9.7 |

**It costs one word.** Across every arm the words met move by at most one out
of 3,660, and nothing that only five channels say is the sole source of
anything on the list.

**The hours are noise, and the table proves it rather than asserting it.**
Dropping the channels is three and a half hours *faster* at the 40-line floor
and one and a half hours *slower* at the 10-line floor. Removing material
cannot genuinely make a schedule shorter, so a negative number here is the
greedy re-ordering itself, not a saving — and the two signs are what make
that certain. It is the same non-monotonicity the floor section runs into at
K=5, and it sets the scale for reading any of these deltas: a few hours
either way, in this experiment, is nothing.

So marking channels machine-made is worth doing for what goes in front of
you, and is free in the schedule. The Channels page is where it is done, and
`video_order.py sweep nomachine` is how this was measured.

## How many unknowns can one sentence carry?

`07-depth-of-gate.csv`, and a plan and a per-word file for each gate.
Everything above holds i+1 to mean *exactly one unknown*. The question this
answers is what that rule costs, and whether the right relaxation is a bigger
number or a different shape — because two unknowns in a four-word line is not
the same thing as two in a twenty-word line.

Two families, both K=1 over the same shelf and the same 3,660 words. A cap
counts unknowns and ignores length; a ratio is unknowns over the sentence's
word count. Both always admit a single unknown, so every gate here is a
superset of i+1 and the hours can only fall.

| gate | hours | videos | lines it admits | words met | words it opens |
|---|---|---|---|---|---|
| i+1 | 202.4 | 677 | 21.1% | 3,556 | 0 |
| ≤10% | 193.5 | 652 | 21.6% | 3,566 | 6 |
| ≤15% | 160.3 | 556 | 25.0% | 3,581 | 18 |
| ≤20% | 120.7 | 453 | **34.8%** | **3,597** | 25 |
| up to 2 | **119.6** | 451 | 44.7% | 3,595 | 28 |
| up to 3 | 95.6 | 374 | 63.9% | 3,601 | 29 |
| any | 86.6 | 340 | 100% | 3,610 | 30 |

**The ratio no longer beats the cap outright, and that is a correction.**
On the corpus before the lemma fixes, ≤20% took 102.6 hours against "up to 2"
at 111.1 -- faster, further and gentler at once. Rebuilt, it is 120.7 against
119.6: **1.1 hours slower**, which is inside the noise of a greedy walk but is
not a win. What survives is the rest of it. ≤20% still reaches two more words,
and still does so while admitting 34.8% of the teachable lines against 44.7% --
a smaller and easier slice for the same time. The claim is now "as fast, on
gentler material", not "faster".

The reason is visible in what each one spends its licence on. A cap hands a
second unknown to every sentence alike, and most sentences here are short:
two new words in a five-word line is 40% of it new, which is the least
supported reading in the corpus and exactly what "up to 2" buys most of. The
ratio spends the same permission only where there are words around the
unknown to carry it. Same relaxation, aimed better.

**Relaxing i+1 buys speed, not reach.** The last column is the goals that are
out of reach under i+1 and that the gate could teach: at most 21 words out of
3,660, and 21 is what dropping the gate *entirely* buys. i+1 is not what
makes the list hard to finish — it is what makes it slow. That the i+1 row
reads 0 is the check that the column is computed right, not a result.

**i+3 is `any` in all but name.** 85.0 hours against 83.8, and once three
unknowns are allowed the gate is doing almost nothing: at that point the
question is not whether to keep a gate but whether comprehensible input is
the model at all, which is a different experiment.

A caveat and a check. The caveat: `target` is the i+1 closure in every row,
so the looser gates are timed on the strict rule's word list. That is what
keeps the rows comparable, and the last column is the size of what it hides.
The check: the generalised gate reproduces the two rules it replaced to the
decimal — i+1 at 194.4 h and `any` at 83.8 h here, and 194.4 and 83.8 from
`sweep`, which walks them through the old code path.

```
PYTHONPATH=. .venv/bin/python experiments/video_order.py depth
```

## A ceiling on how long one video may be

Nobody sits through a two-hour film to learn one word, and the plans have been
full of them: `sowie` cost 204 minutes because its only unblocked sentence was
inside a feature. `shelf(max_minutes=…)` asks the watchable version of the
question. `target` is untouched, so a word whose only source is too long is
reported unmet rather than quietly leaving the list.

| cap | hours | words met | words with no source left |
|---|---|---|---|
| no cap | 633.0 | 3,394 | 69 |
| ≤ 60 min | 523.6 | 3,184 | 137 |
| **≤ 30 min** | **497.2** | **3,089** | 165 |
| ≤ 20 min | 466.1 | 2,890 | 207 |

Thirty minutes is the knee. Going there from no cap costs 305 words for 136
hours -- about 27 minutes saved for each word given up. Tightening to twenty
costs another 199 words for only 31 hours, nine minutes a word, which is a
much worse rate. Capping at thirty is 21% less watching, and a plan that gets
followed at 497 hours beats one that does not at 633.

The shelf loses little to it: 117 videos of 1,478, but 159 hours of 539. The
length is concentrated in a handful of films, which is the same fact the hunt
list reports one word at a time.

## What this does not settle

* **The walks are greedy, and greedy has no guarantee here.** The problem
  contains weighted set cover, and the i+1 gate makes coverage *super*modular
  — a video can be worth more after you have seen another — so even ln(n) does
  not hold. The K=0 covers are honest lower bounds, solved exactly by CBC
  under a relaxed rule; the gap between 130.2 and 193.0 is part ordering cost
  and part greedy slack, and this does not say how much of each.
* **Every number above is a `budget=0` reachability closure**, which is what
  made the held-to-list walks look as dear as they do. The stepping-stone rows
  are the same corpus read without that assumption.
* **The lemmatiser damages the tail it is being asked about.** `EU-Abkommen`
  lemmatises to `eu-abkomma`, `Grenzkontrollen` to `grenzkontroll`; 263
  distinct lemmas end in a lowercase `-a` that should be `-en`. Some of the
  single-source words are single-source because their other occurrences were
  lemmatised into something else.
* **Every count in `07-words-*.csv` is a shelf count, not a corpus count.**
  `sources`, `teaching_sentences` and `any_sentences` see only what the walk
  could watch: videos of 40 lines or more with a running time, plus the
  episodes whose transcript files joined. A word reading `0` there is not
  absent from the corpus, and the table above is the check that proves it.
* **The pricing fix moved the baseline.** Counting only the German half of
  a bilingual transcript makes episodes cheaper, and the i+1 K=1 walk went
  from 193.0 hours to 194.4 — *up*, not down. Cheaper episodes change which
  ones the greedy takes, and a greedy handed a better-priced shelf is not
  guaranteed a better answer. Every number in this document is at the
  corrected pricing; earlier drafts of it were not.
* **Episode running times are estimates, and biased.** 513 of the 2,013
  things on the shelf are priced from their word count — 1,338 of 2,838 at the
  lower floor, so the floor comparison leans on the estimate harder than any
  other number here. Worse than noisy, it is skewed: `episodes()` counts every
  word in the transcript file, and those files carry the English translation
  beside the German. Over 120 files, 162,638 words are counted and 60,155
  reach the corpus — priced at 20.0 hours where the lines that survive are
  7.4. The true German share is somewhere between, since a line can fail for
  being short rather than for being English, but episodes are certainly
  overpriced by a wide margin. That works *against* episodes, so the K=1 floor
  savings are conservative and the shelf's 715 hours are inflated; it is the
  first thing to fix before any of these totals is quoted as a duration.
* **Charges are per-plan shares, not costs that survive a change of plan.**
  Comparing one word's charge across two runs mixes displacement with
  re-attribution, as the floor section shows. Aggregates compare; single words
  do not.
* **One viewing is assumed to teach every word it is the sole unknown for.**
  It will not. The ordering is what this is for, and the ordering only needs
  the relative sizes to be right.

## Reproducing

```
PYTHONPATH=. .venv/bin/python experiments/video_order.py costs
```

Reprices every plan on disk without walking it again: the same state machine
stepped through a saved order, checked at every step against the encounters
and words the plan recorded. Seconds rather than minutes, because choosing is
where the time goes. It fails loudly if the corpus or my known words have
moved, since the prices would then belong to a plan that no longer exists.

```
PYTHONPATH=. .venv/bin/python experiments/video_order.py floor 10
```

Runs the whole suite over a shelf with that floor under the episodes, writing
`-floorN` plans and per-word files as it goes. About 35 minutes, most of it
the `any` cover's integer solve.

`video_order.py stepping` rewalks the two stepping-stone plans from scratch,
which is minutes rather than seconds, and *appends* its summary rows — so
delete the matching `i+1 open` rows from `07-video-order.csv` first, or it
will report the same run twice.
