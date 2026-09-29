# 08 — Can the plan open on easier videos?

The plan's opening felt hard to watch, so the question was whether a different
order could put the easy videos first. It can, a little, and it costs about
twice the hours; the plan already front-loads the readable videos, and most of
what is left is not a property of the order.

The knob tested is a **readability floor**: a video may not be offered until the
reader can already follow some share of its lines. `ease` (experiment 07) only
tilts the rate towards readable videos, and a tenfold difference in teaching
rate walks straight past a threefold difference in readability; a floor refuses
them outright instead. It defers rather than excludes — readability is
recomputed as words land — and comes down by `relax` (10 points) when nothing
clears it, so the tail is still reached.

One shelf, walked at several starting floors, at the defaults the reader uses:
i+1, K=5, 10+ lines, machine-made channels dropped, Super Easy German dropped,
words that can never be taught ignored. 2,923 words in reach, 3,669 items.

## What a floor costs and buys

`line` is the share of a pick's lines with no unknown word — the quantity the
floor acts on. `word` is the share of its unit tokens the reader knows. `level`
is the judge's own CEFR expectation, which does not depend on what the reader
knows; `n` is how many of those picks are levelled at all.

| floor | hours | met | first 10: line | word | level | n | first 50: line | word | level | n | median line |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0% (shipped) | 190.6 | 2,918/2,923 | 29.4% | 82.0% | 1.45 | 2/10 | 24.3% | 79.0% | 1.79 | 17/50 | 23.0% |
| 20% | 245.0 | 2,918/2,923 | 29.4% | 82.0% | 1.45 | 2/10 | 28.5% | 80.1% | 1.54 | 15/50 | 25.8% |
| 30% | 400.0 | 2,918/2,923 | 40.9% | 85.7% | 1.45 | 2/10 | 35.6% | 83.4% | 1.35 | 12/50 | 31.8% |
| 40% | 407.8 | 2,918/2,923 | 49.0% | — | — | — | 43.0% | — | — | — | 32.1% |
| 50% | 407.8 | 2,918/2,923 | 54.3% | — | — | — | 43.0% | — | — | — | 32.1% |

No arm loses a word. Four readings, in order of how much they matter:

- **At 20% the opening does not change at all.** The same first ten videos, the
  same line share, the same word share — for 54 more hours. Whatever the floor
  is buying there, it is not an easier start.
- **Everything from 40% up is one plan.** Same hours, same words met, same
  first-50, same median; only the first few picks differ, because `relax` decays
  a high start to the same walk within a handful of steps. So the floor is
  effectively a switch, and its price is 2.1× the hours.
- **What it buys is small.** Over the first ten at floor 30: line share up 11.5
  points, word share up 3.7, for 209 extra hours.
- **The judge's level does not clearly move.** 1.45 over the first ten at every
  arm, because those are nearly the same videos and only two are levelled. Over
  fifty it falls 1.79 → 1.35, but coverage falls 17 → 12 with it: a mean over a
  shrinking, different subset is not evidence.

**Recommendation: don't add it.** Nothing measured here is worth 1.3–2.1× the
hours. It is a real reordering, not a null one, so it remains available if a
gentler plan is later worth that price.

## Both readability signals track difficulty; the floor moves neither much

Over the 509 levelled videos of the shipped plan, Spearman ρ against the judge's
level:

| signal | ρ |
|---|---|
| line share — what the floor gates on | −0.53 |
| word share | −0.65 |

Word share is the better predictor, but line share is a good one too, so the
floor is not gating on noise — an earlier reading of these correlations as −.19
and −.66 was wrong, and the case against the floor rests on its price, not on
the signal it chooses.

## Why a floor cannot buy much

A line is followable only when every unit in it is known, so at word share `p`
a line of `n` units would be followable with probability `p**n` if its units
were independent. Measured over the 975 distinct videos of the shipped plan, in
plan order, against the seed's 823 known units:

| | observed | mean of p\*\*n | p | mean n |
|---|---|---|---|---|
| the first 10 picks | 38.9% | 28.3% | 83.9% | 8.1 |
| the first 50 | 24.2% | 18.0% | 79.2% | 8.7 |
| all 975 | 12.0% | 7.8% | 71.5% | 9.8 |

The baseline is the mean of `p**n` over the lines, not `p` raised to the mean
length: `p**n` is convex in `n`, so the latter always sits lower and would show
a gap even under perfect independence. Against the right baseline observed still
runs about 1.4× higher at all three scales, so known words do cluster — they
fall in the same short, plain lines.

What matters is the shape rather than the exact factor: at a fixed word share,
line share falls steeply with line length, and line length across the shelf runs
from 4.7 to 15.7 units a video. A floor reaches line share mostly by preferring
short-lined videos, and short lines teach fewer words a minute — which is where
the extra 209 hours go.

*(These are a different instrument from the table above — distinct videos in plan
order against the seed, rather than `followable` at the moment of each pick with
repeats — so the numbers are comparable within each table, not between them.)*

## What the opening already is

The plan front-loads the easy videos without being asked to. Over the first ten
picks word share is 83.9% against 71.5% over the whole plan, and line share
38.9% against 12.0% — three times more followable than the average video it
will reach. The floor-30 arm shows there is more to find, but only about four
points of word share for about twice the hours.

The opening reads as hard because at 823 known units roughly one word in six is
unknown even in the most readable videos on the shelf, and a line averages eight
to ten units. Readability rises mainly as the reader's vocabulary does, which is
a function of time rather than of order.

The levers that remain are therefore mostly not orderings:

- **The gate**, which is already a page option. Its plans cannot be compared as
  they stand: `i2` and `i3` read 217.3 h and 239.8 h against `i1`'s 190.0, but
  they were written on 26 September, before the case frames came off the study
  list and before the corpus was rebuilt, so they are answering a larger
  question. Experiment 07 measured a looser gate as much cheaper on the corpus
  of the day (633 → 397 → 326 h), which is the reason to re-walk them under
  today's corpus rather than to trust either set of numbers.
- **The judge's level**, the best of the three signals at −0.65. Gating on it
  directly is the measurement worth doing, and coverage is the blocker (below).
- A floor that **expires** after N hours, if the goal is only a gentler opening
  rather than a gentler plan. The median moved with the mean at every arm
  (23.0% → 31.8%), so what was measured here is "easier throughout", and that is
  what the hours were spent on.

## Levels are half-stale, and the fix costs coverage first

`corpus/levels.py` draws a video's thirty-line sample from its whole pool of
lines, so a rebuilt corpus re-rolls the draw. 632 of the plan's 975 videos hold
judged lines but only 509 clear the threshold on the sample this corpus draws;
the rest were levelled against a sample that no longer exists.

`levels.py` names the fix — draw the thirty lines with the smallest hash of video
and text, which no rebuild can re-roll — and says to adopt it the next time
every video is levelled anyway. Measured against stored judgments, that switch
is not free:

| draw | levelled now | lines to judge for the rest |
|---|---|---|
| the pool draw, as shipped | 509/975 | 6,021 |
| the hash draw levels.py proposes | 255/975 | 7,010 |

The hash draw asks for lines nobody has judged yet, so adopting it halves
coverage until a pass runs and costs about a thousand more lines. It buys
immunity from the next rebuild. Both counts are for the shipped plan's videos
only, and both need a judge run, so neither has been done.

## Reproducing

Both sweeps and all three checks read the built corpus and stored judgments
only; no judge calls were made. The control arm reads 190.6 h against the
shipped plan's 190.01 h in
`07-plan-i1-k5-floor10-nomachine-noseg-noise.csv`, with identical words met —
0.3%, the tie-break non-determinism noted in experiment 07, not a knob
mismatch. All six defaults were checked as reaching the walk.
