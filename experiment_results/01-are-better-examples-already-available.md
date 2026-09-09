# Are better examples already available, unused?

Numbers from `01-example-choice.csv`, one row per run; the per-step working
for the latest run is in `01-example-choice-detail.csv`.

## What this tests

The roadmap shows one sentence per step, chosen from every sentence in which
that step's word is the only unknown at that point. The picker takes the
shortest, and under study-list counting that means the shortest above the
five-word floor.

This replays the whole walk and records, at every step, **all** the sentences
it could have shown — not just the one it did. If a well-formed sentence is
usually sitting there unused, better examples cost nothing but a better
ranking rule. If not, only restricting the walk would help, and that costs
coverage (experiment 02).

Well-formed means 8-15 words in a single sentence, scored on a curve peaking
peaking at (9, 11) words. It says nothing about meaning.

## History

| run | sentences | steps | with a good candidate | improvable | median candidates | shown | best | median words | on one length | scale |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-09-09 15:20 | 93371 | 3568 | 3391 | 2696 | 12.0 | 0.736 | 0.973 |  |  |  |
| 2026-09-09 15:23 | 93371 | 3568 | 3391 | 0 | 12.0 | 0.973 | 0.973 |  |  |  |
| 2026-09-09 15:27 | 93371 | 3568 | 3391 | 0 | 12.0 | 0.938 | 0.938 | 10.0 | 0.546 | 2 |
| 2026-09-09 16:24 | 115461 | 3576 | 3412 | 0 | 13.0 | 0.943 | 0.943 | 10.0 | 0.581 | 2 |
| 2026-09-09 16:27 | 115461 | 3576 | 3412 | 0 | 13.0 | 0.943 | 0.943 | 10.0 | 0.581 | 2 |
| 2026-09-09 17:02 | 115461 | 3576 | 3412 | 0 | 13.0 | 0.971 | 0.971 | 10.0 | 0.324 | 3 |

Rows are comparable only within a `scale` — `corpus/quality.py` stamps its
version on every run, because a mean from one definition of quality says
nothing about a mean from another.

Shown vs best, across runs: **0.736 → 0.971 (+0.235)**
against **0.973 → 0.971 (-0.002)**. The gap between those
two is what a better ranking rule would close; `best` is the ceiling ranking
alone can reach, and it moves only when the corpus gains better sentences.

## What it means

**Rank, do not restrict.** 95% of steps already have a well-formed sentence among their candidates, so the picker is passing over material it already holds. A better ranking rule cannot cost a single word of coverage, because the candidates per step are unchanged. Only 130 steps (4%) have one candidate, where no rule can help.

## What was passed over, this run

| step shows | it could have shown |
|---|---|
