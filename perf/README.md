# perf — one-off profiling scripts for the 2026-09-22 audit

Read-only. None of these write to Postgres or `state.sqlite3`; the roadmap
scripts run the walk in-process and never call `RoadmapStore.save`. Nothing
here is imported by the application, and the whole directory can be deleted.

Run from the repo root:

    PYTHONPATH=. .venv/bin/python perf/<script>.py

Each finds the repo from its own `__file__`, so they run from any directory
and on any checkout.

| script | what it measures |
|---|---|
| `pgstats.py` | Postgres scan history, table sizes, settings |
| `explain.py` | `EXPLAIN (ANALYZE, BUFFERS)` on the two corpus-load queries |
| `workmem.py` | the same join at `work_mem` 4/16/64/256MB |
| `agg.py` | row-at-a-time vs groupby vs `array_agg` vs `string_agg` vs drain |
| `prof_load.py` | `app.corpus()` split into SQL / transfer / object build |
| `prof_roadmap.py` | phase timings for a 300-step `build-roadmap` |
| `prof_walk.py` | unprofiled walk to 3,902 steps + cProfile attribution |
| `walk_shape.py` | frontier size, goal survival rate, hash-key microbenchmark |
| `skip_cost.py` | cost of the non-goal skip path in `_next_step` |
| `prof_nlp.py` | spaCy parse vs `_units`, profiled |
| `nlp_clean.py` | the same split unprofiled (the honest one) |
| `cache2.py` | `find_best_match` lru_cache sizing |
| `nlp_par2.py` | `analyze_all` at 4/6/8 processes |
| `tts_probe.py` | piper TTS sequential vs a process pool — local, no paid call |
| `reels_flow.py` | open Next, mark a word, open Reels — takes a **copy** of `state.sqlite3` as its argument |
| `walk_ab.py` | one production walk: phase timings and a SHA-256 of the plan |
| `track_cost.py` | what `CorpusIndex.track_goals` costs once |

`AUDIT.md` is the report they produced, with the measured before/after for
the two fixes that were implemented.

`walk_ab.py` is the before/after harness: run it on the tree, then again with
`git checkout HEAD -- roadmap/index.py roadmap/builder.py`, and compare the
`plan_sha256` as well as the timings — the hash is what says the walk still
produces the same roadmap.

Caveat carried from the audit: cProfile inflates Python roughly 2.2x here, so
`prof_*.py` numbers are for *proportions* and call counts. Wall-clock claims
come from the unprofiled scripts.
