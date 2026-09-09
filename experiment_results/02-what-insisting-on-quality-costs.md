# What does insisting on well-formed examples cost in coverage?

Numbers from `02-quality-closure.csv`, one row per run.

## What this tests

A word can only be taught through a sentence where it is the single unknown.
Restricting the walk to well-formed sentences shrinks that pool, so some
words stop being reachable at all. The same walk is run twice over the same
corpus — once with every sentence, once with only the well-formed ones — and
the difference is the price of making quality a *filter* on the walk rather
than a *ranking* over its candidates.

## History

| run | all sentences | reached | well-formed | reached | words lost | share |
|---|---|---|---|---|---|---|
| 2026-09-09 15:20 | 93371 | 3568 | 33242 | 3394 | 174 | 0.0488 |
| 2026-09-09 15:23 | 93371 | 3568 | 33242 | 3394 | 174 | 0.0488 |
| 2026-09-09 16:27 | 115461 | 3576 | 41394 | 3414 | 162 | 0.0453 |
| 2026-09-09 17:03 | 115461 | 3576 | 41394 | 3414 | 162 | 0.0453 |

Words lost across runs: **174 → 162 (-12)**.

## What it means

Restricting costs 4.5%. Cheap — but only worth paying if ranking has already been tried, since ranking costs nothing.

## A caveat on reading this

A single closure cannot see ordering. A word taught from a poor sentence in
the unrestricted walk is not necessarily lost in the restricted one — it may
arrive later, from better material, once other words are known. The figure
is therefore an upper bound on what restricting really costs.
