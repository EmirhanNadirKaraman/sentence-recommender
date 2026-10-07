# Web capacity audit

Run from the repository with the existing database available:

```sh
.venv/bin/python benchmarks/web_capacity.py --out /tmp/web-capacity.json
.venv/bin/python benchmarks/web_capacity.py --profile --users 1 --rounds 1 --routes /frontier /anki --out /tmp/web-profile.json
.venv/bin/python benchmarks/cover_capacity.py /tmp/cover-capacity.json
```

These scripts exercise existing data, not empty fixtures. The HTTP harness
starts an ephemeral loopback-only server using the real router. Synthetic
sessions have separate application/viewer caches but read the same existing
owner state and list; there are no real accounts created and no grade/save
requests. GET handlers can refresh derived score/cache state. Do not run it
as a public server or assume it represents users with different lists.

`--profile` adds substantial overhead: use it for call counts/attribution,
not latency comparisons. macOS RSS excludes compressed memory; the JSON also
records vmmap physical footprint when available. Neither memory value
includes PostgreSQL. Resource pressure and other local processes affect
measurements. The four-user test is a small finite load probe, not a soak test.

The recorded 2026-10-07 outputs are explained in
[hosting-capacity-report.md](../docs/hosting-capacity-report.md). The first
diagnostic run used a wrong live-search URL; those HTTP errors are a harness
mistake, and the corrected final run successfully tests `/api/cover-search`.
The cover record distinguishes covered targets from `(video, target)` witness
pairs; the initial logging counted the latter under `covered`, corrected in
the artifact using audited optimal coverage and unreachable target counts.

No model/generation endpoint is called. Cover calculations do not save lists.
All media playback, frontend rendering, real login and write traffic are
outside these probes. The older write-isolated four-reader harness remains
available in `perf/four_readers.py`.
