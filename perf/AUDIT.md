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
| 1 | Cold corpus load repeated per process and per source | cold `/` 10.71 s vs warm 0.068 s; every CLI command pays it; `Viewer._corpora` keyed per source | cache the built corpus (mmap/arrow) or keep one warm process | −10 s per cold start, the only latency a human waits on | M |
| 2 | Walk rescans whole frontier each step | frontier grows 6,916 → 17,710 units by step 600 while goals plateau at ~3,000. The guard sequence at `roadmap/builder.py:154` costs a measured **2.01 ms/step** more than the same loop over goals alone | maintain a goal-candidate dict incrementally **in `CorpusIndex`** — a per-step `goals & candidates.keys()` still hashes every frontier unit and wins much less | 7.8 s over 3,902 steps = **25.7% of the walk**; 30.5 s → ~23 s (projected) | S |
| 3 | `work_mem=4MB` spills the hot join | `EXPLAIN ANALYZE`: Batches 8, temp read+written 17,151 blks = **134 MB temp I/O**; exec 2,859 ms → **2,053 ms** at 64MB | `SET work_mem` on the session, or postgresql.conf | −0.6 s per corpus load, −28% server time | XS |
| 4 | 3.18M unit rows shipped to build 310k objects | transfer-only 2.41 s vs as-shipped 7.98 s; `string_agg` variant 5.74 s | aggregate units server-side | −2.2 s per load | S |
| 5 | `Unit` hashing dominates the walk | `Unit.__hash__` **22,797,527 calls** in 600 steps; tuple keys 2.53x faster, int keys 3.88x | intern units to ints inside the index | walk −20–30% est. | L — `Unit` has a `__reduce__` because it crosses process boundaries, and it flows through the store, SRS and web pages |
| 6 | `analysis_processes: 8` is past the knee | best-of-3: 4 procs **1,402 sent/s**, 6 procs 1,390, 8 procs 1,236. M1 is exactly 4P+4E; 8 was slowest in all three reps | set 4–6 | −12% on build-corpus | XS |
| 7 | `find_best_match` lru_cache thrashing | `maxsize=4096`, **currsize=4096**, hit rate 68.6%; unbounded → 70.4%, **−5.2% on `_units`** | raise maxsize | −1.5% of build-corpus | XS |
| 8 | `phrase_finder` imported twice | `sys.modules` holds `phrase_finder` *and* `matcher.phrase_finder` as separate objects; only the first is used — two lru_caches, two trigram tables | single import path | correctness+memory, not speed | XS |
| 9 | `find_expression_rows` is 27 expressions × every token | 1,502,680 `_match_row` calls for 4,000 sentences | index the 27 rows by first literal word (all 27 have one; 18 distinct) | ~3% of build-corpus | S |
| 10 | 1,240 MB of write-only tables | `sentence_to_phrase` 526 MB + `word_to_sentence` 361 MB + `sentence_to_grammar_rule` 353 MB = 36% of the 3,475 MB DB, read by nothing | drop or move | disk + vacuum, not query time | S |
| 11 | Unguarded `Viewer._corpora` | ~60 concurrent cold requests each started a full load; RSS 1.6 GB, no reply in 300 s | one lock around the cache fill | local single-user, low severity | XS |

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
3. **#3 + #6 config** — `work_mem`, `analysis_processes: 4`. Two lines,
   both measured.

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
