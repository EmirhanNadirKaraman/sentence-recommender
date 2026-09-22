# Performance audit — sentence-recommender

Machine: Apple M1, 8 cores (4P+4E), 16 GB, macOS 25.2. Python 3.12.0,
PostgreSQL 14.8, spaCy `de_core_news_md`. Measured 2026-09-22.
No paid API was called. No production code changed; no store written.

## Recommendation

**Keep Python.** Not because the hot work is all native — that is only true of
the NLP half. Because the one workflow that *is* Python-bound, the greedy walk,
is 30.5 s inside a ~110-minute rebuild chain, and roughly a quarter of it is
recoverable in Python without touching the language.

The honest caveat: the walk really is 88% Python bytecode with near-zero native
time, and Rust would win real time there. It is simply the wrong 30 seconds to
spend a rewrite on. If `build-roadmap` becomes something you run fifty times a
day, revisit it — with `CorpusIndex` as the component, not the backend.

## Where the time actually goes

| workflow | wall | native / I/O | Python bytecode |
|---|---|---|---|
| web page, cold `/` | 10.71 s | ~6 s Postgres+libpq | ~5 s object build |
| web page, warm `/` | 0.068 s | — | — |
| `build-roadmap` (3,902 steps) | ~42 s | ~5 s (12%) | ~37 s (88%) |
| `build-corpus subtitle` (262k), **analysis phase only** | ~3.1 min | 71% spaCy | 29% |
| rebuild chain (7 steps) | ~110 min+ | ~99% external inference + native media tooling | ~0.5% |

The rebuild chain is the thing that actually takes an afternoon: translations
82.5 min, TTS 26.1 min (your own `out/logs/rebuild_chain.log`), plus step 7's
4.7 GB of episodes through ffmpeg — native, and untimed here. The greedy walk
is 30.5 s of it.

`build-corpus` above is the **analysis phase only** (`analyze_all` over 24k real
sentences, extrapolated). The real command also pulls subtitle rows, runs
`MergeCorrector`, filters, and writes 450k sentence + 3.18 M unit rows through
`execute_values` — none of which I timed.

## Bottlenecks

| # | bottleneck | evidence | fix | impact | effort |
|---|---|---|---|---|---|
| 1 | Cold corpus load repeated per process and per source | cold `/` 10.71 s vs warm 0.068 s; every CLI command pays it; `Viewer._corpora` keyed per source | **done** — `Once` shares one load across threads | 3 concurrent cold `/` **43.3 s → 11.5 s**; Reels **9.91 s → 0.03 s** | M |
| 2 | Walk rescans whole frontier each step | frontier grows 6,916 → 17,710 units by step 600 while goals plateau at ~3,000. The guard sequence at `roadmap/builder.py:154` costs a measured **2.01 ms/step** more than the same loop over goals alone | maintain a goal-candidate dict incrementally **in `CorpusIndex`** — a per-step `goals & candidates.keys()` still hashes every frontier unit and wins much less | **measured −71%**: 34.57 s → 9.97 s over 3,932 steps, plan byte-identical. The 25.7% projection was low — see the correction below | S |
| 3 | `work_mem=4MB` spills the hot join | `EXPLAIN ANALYZE`: Batches 8, temp read+written 17,151 blks = **134 MB temp I/O**; exec 2,859 ms → **2,053 ms** at 64MB | **done** — set in `DatabaseConfig.dsn_kwargs` | measured **−23% on the query, −9% on the whole load**; spill gone | XS |
| 4 | ~~3.18M unit rows shipped to build 310k objects~~ **CLOSED** | re-measured interleaved at `work_mem=64MB`: as-shipped **8.08 s**, `string_agg` **9.36 s** — the variant is 16% *slower*. The original 5.74-vs-7.98 gap was cache warming between two single runs | none | — | — |
| 5 | `Unit` hashing dominates the walk | `Unit.__hash__` **22,797,527 calls** in 600 steps; tuple keys 2.53x faster, int keys 3.88x | **done** — units numbered inside `CorpusIndex`, `Unit` at the door | measured **walk −43%, 1.76x**; both plans byte-identical | L |
| 6 | `analysis_processes: 8` is past the knee | best-of-3: 4 procs **1,402 sent/s**, 6 procs 1,390, 8 procs 1,236. M1 is exactly 4P+4E; 8 was slowest in all three reps | **done** — set to 4 | −12% on build-corpus, on a quiet machine | XS |
| 7 | `find_best_match` lru_cache thrashing | `maxsize=4096`, **currsize=4096**, hit rate 68.6%; unbounded → 70.4%, **−5.2% on `_units`** | **done** — 65,536 | −17% on `_units` single-process; **does not show through the worker pool** | XS |
| 8 | ~~`phrase_finder` imported twice~~ **WITHDRAWN** | an artifact of the audit's own diagnostic: `perf/nlp_clean.py:15` does `import matcher.phrase_finder`, which is what created the second module object. The real app loads exactly one | none needed | — | — |
| 9 | `find_expression_rows` is 27 expressions × every token | 1,502,680 `_match_row` calls for 4,000 sentences | **done** — the rows whose first element is a required literal are tried only where that word occurs | measured **−40% on `_units`, −5% on build-corpus**; units byte-identical | S |
| 10 | ~~1,240 MB of write-only tables~~ **WITHDRAWN** | `sentence_to_phrase` 526 MB + `word_to_sentence` 361 MB + `sentence_to_grammar_rule` 353 MB = 36% of the 3,475 MB DB, read by nothing *in this project* | **do not drop** — see the correction below | — | — |
| 11 | Unguarded `Viewer._corpora` | ~60 concurrent cold requests each started a full load; RSS 1.6 GB, no reply in 300 s | **done** — `Once` | one load, not N; peak 1,814 MB for 8 concurrent | XS |

## The language question

**How much could replacing Python realistically win?**

- `build-corpus`: 71.4% is spaCy's Cython parser (800 sent/s parse vs 1,994
  sent/s for the project's own `_units`). Amdahl ceiling from rewriting the
  Python 29%: **1.4x**. A rewrite still calls spaCy or reimplements German
  lemmatisation — which is the product.
- `build-roadmap`: 88% Python, ~0% native library time. This is the one place
  a rewrite genuinely pays: 30.5 s → plausibly 1–3 s in Rust. But see below.
  Note the walk is **linear** in steps (7.0–8.3 ms/step from 100 to 3,902), so
  this is a constant-factor problem, not a complexity one.
- Web serving: warm requests are 68 ms and the process is idle. Nothing to win.
- Rebuild chain: 99.5% is waiting on the LLM endpoint and TTS. Irrelevant.

**Is the expensive work already native?** Half of it. spaCy yes; the greedy
walk no. The walk is hash-set graph traversal over 229k sentences — exactly
what Python is worst at, and it shows: 22.8M `Unit.__hash__` calls in 600 steps.

**Would a Rust component called from Python be sufficient?** Yes, and it has a
clean boundary: `CorpusIndex` + `RoadmapBuilder._next_step` (~600 lines, units
in, step out). That is the only component worth considering. Do #2 and #5 first
and re-measure — they plausibly land the walk near 15–20 s. Whether *that* is
worth a second language stays a live question, not a closed one: it depends
entirely on how often you run `build-roadmap`. Once per rebuild chain, no. Fifty
times a day while tuning roadmap parameters, it starts to pay.

**What would a full rewrite cost?** Reimplementing spaCy German lemmatisation,
`phrase_finder` (1,153 lines of tuned German grammar rules), the two-pass
majority vote, and losing `spacy-lookups-data` — whose absence the README
records as measurably worse output. The corpus content is the asset; the
runtime is not the constraint. Not justified by these measurements.

## Three next steps

1. **#2 goal-candidate index** — biggest single CPU win for the smallest
   change (measured 25.7% of the walk), and it sets the baseline any native
   component would have to beat.
2. **#1 warm corpus** — the only latency a human waits on (10.7 s → 0).
3. ~~**#3 + #6 config**~~ — done; see the section below. Items 4, 5, 8 and 9
   remain open, and 10 is withdrawn.

## Measured after implementing #1 and #2 (2026-09-22)

Same machine, same corpus (229,306 well-formed sentences of
`generated+subtitle+transcript`, strict counting, beginner seed), same
scripts. Before/after taken in one session: the tree was reverted to `HEAD`
with `git checkout HEAD -- <paths>` for the "before" run and restored after,
so both numbers come off the same warm database and the same machine load.

### #2 — the goal-candidate index

| walk | before | after | change | plan SHA-256 |
|---|---|---|---|---|
| plain, 3,932 steps | **34.57 s** (8.79 ms/step) | **9.97 s** (2.54 ms/step) | **−71%, 3.47x** | `34383b81…5869827a` both |
| `--relax`, 3,952 steps | **32.24 s** (8.16 ms/step) | **9.84 s** (2.49 ms/step) | **−69%, 3.28x** | `c3683dd9…7dc64397` both |
| `build-roadmap` end to end | 45.65 s | 24.57 s | −46% | |

The hash covers every step's position, unit, score, gain, teaching sentence,
deck, and readable count across the whole plan. Ordering and tie-breaking are
preserved by construction and by measurement, not by assertion.

The relaxed walk is measured separately because it is the one branch the goal
view does not cover: `_relaxed_step` scans the lookahead rather than the
frontier, and it learns a second unit per step (`beside`) that may not be a
goal. Same plan, same 3,952 steps, same hash.

`track_goals`' one-off snapshot of the frontier is **0.37 ms** (best of 5, at
a 2,492-unit frontier against 4,051 goals). The `builder_s` phase read 0.42 s
before and 1.62 s after in the two walk runs; that gap is `gaps_by_video` and
GC variance between runs, not this change.

**The audit predicted −25.7%; the measurement is −71%.** The method was the
flaw, not the arithmetic: `skip_cost.py` sampled five points inside the first
600 steps of a 3,932-step walk — the first 15% — and the cost it was sampling
grows monotonically, because the frontier keeps growing while the goals among
it level off. The mean over the sampled window was ~12,900 frontier units; the
mean over the whole walk is far larger. That 8.79 → 2.54 ms/step leaves 2.54 ms
as the *entire* remaining per-step cost says the guard sequence was about
seven tenths of the walk, not a quarter.

Treat the earlier 2.01 ms/step as a floor measured early, not a mean, and
sample across the whole range before projecting from a microbenchmark again.

### #1 — concurrent cold corpus loading

Bounded test: three concurrent cold `GET /` against a freshly started server,
no memory spike recreated.

| | before | after |
|---|---|---|
| 3 concurrent cold `/` | **43.33 s each** | **11.48 s each** |
| warm `/` after | — | 0.11 s |
| peak RSS, 8 concurrent cold | not run (the audit's 60-request run reached 1.6 GB and answered none in 300 s) | **1,814 MB** — one corpus, not eight |

11.48 s for three concurrent requests is what one cold request costs
(10.71 s measured in the audit), so the load is now shared rather than
repeated. Eight concurrent cold requests answer in 18.7 s each — still one
load, degrading with thread contention on the per-request rendering rather
than multiplying the load.

**Process boundary.** `serve` is one process, `ThreadingHTTPServer`, a thread
per request, and every request it answers goes through one `Viewer`. The lock
covers all of them. It is an in-process lock and shares nothing across
processes: run two servers and each has its own `Viewer`, its own cache and
its own locks, so each pays its own cold load and holds its own ~1.5 GB. That
is the model today and the fix is per-process by construction. Blocking a
request thread is the right thing here — there is no event loop to starve, and
the thread has nothing else to do but wait for the rows it was asked for.

**Prewarming was not added.** It is a separate lever, not a substitute: safe
initialisation is what stops the herd, and prewarming only moves the first
load earlier. Adding it would put a flag beside the thing rather than
changing the thing, and it would charge every `serve` start ~10 s and ~1.5 GB
whether or not anyone opens a page that needs a corpus. If it is wanted later
the place for it is `LocalServer`'s startup, before `serve_forever`.

### Reproducing these

```
PYTHONPATH=. .venv/bin/python perf/walk_ab.py after  /tmp/after.json
PYTHONPATH=. .venv/bin/python perf/walk_ab.py after  /tmp/after-relax.json relax
git checkout HEAD -- roadmap/index.py roadmap/builder.py
PYTHONPATH=. .venv/bin/python perf/walk_ab.py before /tmp/before.json           # then restore
PYTHONPATH=. .venv/bin/python perf/walk_ab.py before /tmp/before-relax.json relax
PYTHONPATH=. .venv/bin/python perf/track_cost.py
PYTHONPATH=. .venv/bin/python -m pytest tests/test_once.py tests/test_goal_candidates.py -q
```
The concurrency figures come from starting `main.py serve --port <p>
--no-browser` in the background and firing N concurrent `curl` requests at
`/` before any warm-up.

### Limitations of these numbers

- One run each for the walk before/after. The gap (34.57 s vs 9.97 s) is far
  outside the run-to-run variance seen elsewhere, and the plan hash proves the
  two did identical work, but neither is a best-of-N.
- The corpus load inside those runs varied 8.76 s to 10.65 s, so
  `build-roadmap` end to end carries that noise; the walk figure does not.
- The `/` page timings are one cold burst each. `/` also renders, so the
  per-request numbers are not pure corpus-load cost.
- `_relaxed_step` still scans the full lookahead and filters it by goals. It
  runs only when `_next_step` finds nothing, so it is off the hot path and was
  left alone — the brief was the candidate subset, not the lookahead. It is
  covered by measurement (the `--relax` row above) and by a test, but it is not
  itself made faster.
- `Once._locks` is never pruned. The keyspace is closed — source × counting
  mode — so it cannot grow without bound, but a `Viewer` per saved word list
  means one `Once` per list rather than one overall.
- Nothing here re-measures items 3–11 of the table above; they are untouched.

## Reels: why it was slow, and what it costs now (2026-09-22)

Reported as "clicking Reels took a long time". Three compounding causes, all
measured against a copy of `state.sqlite3` on the `subtitle` build.

**1. The reel loaded the corpus a second time.** `_grouped()` called
`app.corpus(*builds, strict=True)` — byte for byte the call `corpus_for` makes
and caches. In one process:

```
scope()      [what '/' does]     9.65s   rss 1315 MB
corpus_for() again               0.00s   rss 1315 MB
_grouped()   [what /reels does]  8.88s   rss 1965 MB
```

Both held 214,098 sentences and **shared not one object**. `_grouped` now
groups `corpus_for(source, False)`; with the corpus warm it costs **22 ms**.

**2. Marking any word invalidated every stored video score.** `_score_stamp`
is `fingerprint|SCORE_VERSION|known-version`, and the `known_units` trigger
bumps the last on every mark.

**3. The incremental repair did not run.** `_rescore_locked` opened with
`if not self._ranked: return`, so a word marked from Next, Review or over MCP
moved the stamp and repaired nothing. `_repairable()` now also accepts a
source whose corpus is already in memory, and the rows are read back with
`ScoreStore.latest` when the process holds no ranking.

### Measured, same flow, before and after

| | before | after |
|---|---|---|
| open `/`, mark a word, **click Reels** | **9.91 s**, rss 1,914 MB | **0.03 s**, rss 1,288 MB |
| `mark_known` POST latency, most-said word | 5.3 ms | **5.3 ms** (unchanged) |
| the same mark's background rescore | — (skipped, cache left stale) | 446 ms on the `rescore` thread |
| fresh process, Reels first, stamp valid | 0.04 s, no corpus loaded | 0.03 s, no corpus loaded |

The mark itself did not get slower: the repair runs on the daemon thread the
POST already hands off to. What changed is that it now runs at all, so the
next reel load reads rows instead of rebuilding them.

### A hazard found while writing it

`ScoreStore.latest` reads stored rows *without* checking their stamp, so
repairing a few videos and restamping would have declared every untouched row
fresh — including rows computed by an analyser that no longer exists. That is
the failure `SCORE_VERSION` was added for. `ScoreStore.stamp(source)` now
exposes the stored stamp and `_rescore_locked` repairs only when the
fingerprint and scoring version are unchanged; anything else is left for
`_compute` to rebuild. Two tests cover it.

### A stale cache fixed on the way

`_corpora` was cleared in three places and `_videos` in one. After
`_catch_up_now` analysed a newly scraped video, the reel kept the grouping it
made before — so the video just added was missing until a restart. Both, and
`_video_levels`, `_spoken` and `_unit_videos`, now go through
`Viewer._forget_corpus()`.

### Limitations

- One run per row; the corpus load inside them varies 8.2–10.7 s as recorded
  above. The Reels figures (9.91 s vs 0.03 s) are far outside that.
- Scenario "fresh process, Reels first" does not discriminate between the two
  versions — the setup pass leaves a valid stamp either way. It is there to
  show that a valid stamp serves the reel without a corpus at all.
- The repair is deliberately skipped in a process holding neither a ranking
  nor a corpus, which is the MCP server. Marks made there still leave the
  stamp behind and the next reader still recomputes — now at 0.6 s warm
  rather than 9.9 s.
- `perf/reels_flow.py` reproduces the table; it takes a copy of
  `state.sqlite3` as its argument and refuses to run against anything else.

## Items 3, 6, 7 and 10 (2026-09-22)

### Two of the eleven findings were artifacts

Worth stating rather than quietly deleting the rows. Item 8 was caused by the
measurement itself, and item 10 by reading "read by nothing" as "unused".
Both were plausible, both were in the report, and neither survived being
checked before the code was changed.

### 8 — withdrawn, and the audit measured its own script

`corpus/analyzer.py` puts `matcher/` on `sys.path` and imports
`phrase_finder` as a top-level module. Nothing in the project imports
`matcher.phrase_finder`. The audit's own `perf/nlp_clean.py` did, which is
what put a second module object in `sys.modules` — a second lru_cache and a
second trigram table that exist only while that script is running. A clean
`Application()` loads one:

```
phrase_finder modules loaded by the real app: ['phrase_finder']
```

Nothing to fix.

### 10 — withdrawn, and the audit was wrong to suggest it

"Read by nothing" was true and beside the point. `ingest/video.py:182` calls
`pipeline.populate` — language-app's own scraper, borrowed rather than
reimplemented — and that *writes* four of them:
`sentence_to_grammar_rule` and `word_to_sentence` directly,
`phrase_blueprint` and `sentence_to_phrase` through `insert_phrases`.
Migration `85f526a480c5` exists for exactly this and says so: "a missing
table is not a slow query, it is a crash halfway through a scrape."

Dropping them would break `add-video` and `add-channel`. The 1.2 GB is the
price of not maintaining a second subtitle parser. Nothing was dropped.

### 3 — `work_mem`, measured

Set on the connection in `DatabaseConfig.dsn_kwargs` rather than in
`postgresql.conf`: it is this project's query that wants it, and a setting
carried in the repo is one a second machine gets for free.

| | before (4MB) | after (64MB) |
|---|---|---|
| unit join, server `Execution Time` | 2,859 ms, **Batches: 8** | **2,031 ms, Batches: 1** |
| temp file I/O | 17,151 blocks read + written (134 MB) | **none** |
| query + fetch, best of 5 | 4,001 ms | **3,087 ms** (−23%) |
| `CorpusStore.load()`, best of 3, interleaved A/B/A/B | 11.30 s / 11.43 s | **10.21 s / 10.54 s** (−9%) |

The first single measurement of `load()` showed no change and was wrong —
the saving is ~1 s inside a 10 s operation whose variance is comparable, so
it only appears when the two are interleaved and repeated.

### 6 — `analysis_processes: 8 → 4`

The old comment justified eight with a measurement against spaCy's own
`n_process` (990 sent/s vs 540) — that compared this module with the thing
it replaced, not eight workers with four. Against four, eight loses: best of
three on 24,000 real sentences, four gave **1,402 sent/s**, six 1,390, eight
1,236, and eight lost every repeat. Four performance cores and four
efficiency cores; the second four cost more in contention than they return.

### 7 — `find_best_match` cache, 4096 → 65,536

Single process, 40,000 sentences: at 4,096 the cache held 4,096 entries
against **21,236 distinct words** and hit 70.9%; at 65,536 it holds them all
and hits 77.9%, and reading the units off those sentences went **32.3 s to
26.8 s (−17%)**. Bounded rather than `None` because the key is a corpus word
and the corpus decides how many there are; unbounded measured no better.

**It does not show in the parallel path.** Interleaved A/B/A at four
processes: 592, 596, 609 sent/s — noise. spaCy's parser is 71% of analysis
and is unaffected, so a 17% win on the Python 29% is ~5% overall, inside the
run-to-run spread. Kept because it is free and real; not claimed as a
throughput win.

### 4 — closed, the variant is slower

Re-measured the way the later items were: interleaved, three runs each, at
the `work_mem` now in force, on a machine at load 1.7.

| | best of 3 | median |
|---|---|---|
| as shipped, row at a time | **8.08 s** | 9.05 s |
| `string_agg`, one row per sentence | 9.36 s | 9.80 s |

Both produce identical units and identical surfaces over all 309,883
sentences, so the variant was correct — just slower by 1.28 s (16%). The
original reading (`string_agg` 5.74 s against as-shipped 7.98 s) came from
`perf/agg.py`, which ran each variant once in sequence; inside that same
script the *same* query timed 1.78 s and 4.35 s on two runs. The gap was the
page cache warming up, not the aggregation.

Nothing changed. This is the third of eleven findings not to survive being
checked, after 8 and 10.

### 9 — the expression scan, done

25 of the 27 rows open with a literal word that must be there, so they can
only begin where that word does. The sentence is indexed once — lowercased
token to positions — and each row is tried only at its own openings. The two
rows that open with an optional element still get the full walk, since
`_match_row` may skip it.

The order is untouched, and the order is what decides the outcome: the first
expression takes its words out of play before the second is tried. This
narrows *where* each row is attempted, never which row goes first.

| | old | new |
|---|---|---|
| the function alone, 20,000 sentences | 2.603 s | **0.657 s** (3.96x) |
| `_units()`, 20,000 sentences | 6.50 s | **3.86 s** (−41%) |
| `build-corpus`, 1 process, 12,000 sentences | 28.42 s | **26.92 s** (−5%) |

Units **identical** over 20,000 real sentences: 210,092 units and the same
SHA-256 across every sentence's units, its surfaces, and the corpus-wide
`Evidence` tally the second pass votes on.

−5% and not −41% because spaCy's parser is the other 71% of analysis and is
untouched. `consumed` is empty on entry in the real path —
`extract_german_logic` builds it immediately above the call — so the
narrowing cannot interact with words already claimed.

### 5 — units numbered inside the index, done

`CorpusIndex` keys `_by_unit`, `_candidates`, `_pending`, `_goal_candidates`
and the known set by integer. `Unit` is unchanged — its `__reduce__`, the
store, the SRS and the web pages never see a number. The numbering stops at
the door: `candidates()`, `pairs()`, `containing()`, `known` and `granted`
still speak `Unit` and translate on the way out, which costs nothing because
their callers ask once, not once a step. `RoadmapBuilder` uses the
`_ids` variants, because it is the thing asking millions of times.

Each sentence gets a `frozenset[int]` built once, so `_register`'s
`sentence.units - known` is an integer set difference rather than a
conversion pretending to be one — measured 2.2x on that line alone. The
builder resolves per-number arrays for key, kind, weighted priority and
goal membership in `__init__`, so `_score` is two list indexes where it was
two dict lookups with `Unit` keys.

| | before | after |
|---|---|---|
| walk, 3,932 steps | 15.15 s | **8.63 s** (1.76x, −43%) |
| index construction | 1.00 s | 1.55 s (the interning pass) |
| builder `__init__` | 0.59 s | 0.65 s (the arrays) |
| all three together | 16.74 s | **10.83 s** (−35%) |
| plain plan SHA-256 | `34383b81…` | `34383b81…` **identical** |
| `--relax` plan SHA-256 | `c3683dd9…` | `c3683dd9…` **identical** |

The score arithmetic is kept in its original order — `gain + weight *
priority`, then `+= GOAL_BONUS` — rather than folding the bonus into the
precomputed term. Floating point is not associative and the score breaks
ties, so the fold would be a different number and could be a different plan.

Against the walk as it stood before any of this work, measured on the same
machine within the hour: 47.37 s to 8.63 s.

### Absolute timings drift across a session; ratios do not

The walk measured 34.57 s before the goal index and 9.97 s after, back to
back. Re-measured hours later on the same machine at a *lower* load average,
the same two builds gave 47.37 s and 15.15 s — both about 1.4x slower, same
plan hash, same 3,932 steps, ratio 3.13x against the 3.47x first reported.
Nothing had changed but the machine, most likely thermal after an afternoon
of benchmarking.

Quote the ratio, measure both sides back to back, and treat any absolute
second in this document as good only for the hour it was taken in.

### A caution about all the throughput numbers here

The 4-vs-8 and the 1,402 sent/s figures were taken on a quiet machine. Re-run
later with VS Code at 71% CPU and a load average near 5, the same benchmark
gave **~590 sent/s regardless of any setting** — a 2.4x collapse that has
nothing to do with the code. Any re-measurement of `build-corpus` throughput
should check `uptime` first, or it will measure the editor.

## The rebuild chain (2026-09-22)

The audit stopped at the interactive app and said the ~110-minute chain was
"~99% external inference and native media tooling" and therefore not a
Python problem. That is true and still leaves two questions worth asking of
the configuration.

### The gloss pool used two of six slots

`translate-sentences` sizes its pool from the server — `workers =
client.slots() or WORKERS` — and records why: one slot answered 1.15
sentences a second and seven answered **12.4**. `gloss-deck` was pinned at
`workers: int = 2`, with an argparse default of 2 over the top of it. The
endpoint in `.env` reports `total_slots: 6`, so four sat idle for the 82.5
minutes step 2 of the chain takes (3,888 glosses, 0.79 a second).

`deck.gloss.run` documents why two rather than four: a llama.cpp server
divides its context into one slot per parallel request and reserves the KV
cache for each, and concurrency past the slot count produced a 40–60%
failure rate. That division happens when the *server* starts, though. Filling
slots it has already reserved cannot shrink anything; leaving them empty only
wastes them. So the fix is to ask, not to raise: `client.slots() or 2`, the
same line `translate-sentences` has.

Not yet measured end to end — that needs a real gloss run against the
endpoint. The mechanism is the one already measured in
`translate_sentences.py`, and the slot count is verified.

### TTS is already parallel — withdrawn

`deck/speech.py:synthesise` is a plain sequential loop, which looked like
seven idle cores. It is not: ONNX Runtime threads a single piper inference
internally, and a process pool makes it **slower**, because each process
spawns its own thread pool and they contend for the same four performance
cores.

| | wall | cpu | cores busy | rate |
|---|---|---|---|---|
| sequential | 14.83 s | 55.84 s | **3.76** | 3.24 lines/s |
| pool of 2 | 16.41 s | 88.96 s | 5.42 | 2.93 lines/s (0.90x) |
| pool of 4 | 22.55 s | 131.63 s | 5.84 | 2.13 lines/s (0.66x) |

48 real lines, `de_DE-thorsten-medium`. The measured 2.44 pieces a second in
the 26.1-minute chain step is close to the 3.24 here, and that gap is the
second voice and the disk writes rather than idle silicon. Nothing to do.

This is the fourth suggestion in this document not to survive measurement,
after 4, 8 and 10 — and the only one that was caught *before* the code was
written rather than after.

## Reproducing

Scripts are in **`perf/`** (added by this audit, deletable, read-only —
none write to Postgres or `state.sqlite3`, and the roadmap ones never call
`RoadmapStore.save`). `perf/README.md` indexes them.
```
PYTHONPATH=. .venv/bin/python perf/<script>.py      # from the repo root
pgstats.py    Postgres scan history, sizes, settings
explain.py    EXPLAIN (ANALYZE, BUFFERS) on the two load queries
workmem.py    the same join at work_mem 4/16/64/256MB
agg.py        row-at-a-time vs groupby vs array_agg vs string_agg vs drain
prof_load.py  app.corpus() split into SQL / transfer / object build
prof_walk.py  unprofiled walk to 3,902 steps + cProfile attribution
walk_shape.py frontier size, goal survival rate, hash-key microbenchmark
skip_cost.py  cost of the non-goal skip path in _next_step
nlp_clean.py  unprofiled spaCy-parse vs _units split
nlp_par2.py   analyze_all at 4/6/8 processes
```
Cold web load: start `serve` on a spare port via a background runner, hit each
route once sequentially, then again.

## Limitations

- **cProfile inflates Python ~2.2x** (`_units` 5.78 s profiled vs 2.60 s not).
  Every headline number here is unprofiled; profiles are used only for
  *proportions* and call counts.
- **No cold-disk measurement.** Dropping the OS page cache needs sudo on macOS,
  so "cold" means cold process against a warm-ish OS/PG cache. `shared hit` vs
  `read` in the EXPLAIN output stands in for it. The corpus load varied 8.2 s
  to 15.3 s run to run for this reason — treat it as a range. The
  native/Python split given for the 10.71 s cold page load is borrowed from the
  15.3 s profiled run, so read it as proportions, not as that run's seconds.
- **Single-run numbers** where noted: the corpus-load split and the transport
  variants are one run each; `find_expression_rows`' share is profiled only.
  The process-count result is best-of-3 and consistent in direction.
- **Estimates are marked "est."** No. 2's 25.7% is measured (the real guard
  sequence over the real frontier at five sampled steps, 200 reps each), but
  the resulting 23 s walk is a projection, not an implemented change — and a
  conservative one, since the frontier was still growing at step 600. No. 5 is
  a microbenchmark ceiling, not a design.
- **Not measured:** ingestion (`add-video`/`hunt`, needs YouTube + cookies),
  anything LLM-shaped (not run, per your instruction), `export-deck`/`bundle-deck`
  (ffmpeg), and SQLite write paths under real concurrency.
- Postgres stats are cumulative since 2026-09-11 and include your own runs and
  a past ingestion, not just this audit.
