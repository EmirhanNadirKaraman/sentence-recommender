"""Where experiment results live.

A CSV per experiment, appended to on every run, one row per run. The reports
are written from these files rather than from the run that happened to
produce them, so the question they answer is not "how is it now" but "is it
getting better" — which is the only question worth asking while the corpus
keeps growing.

Raw numbers here, prose in the reports. A row is never rewritten: a run that
measured a worse corpus is part of the record.
"""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

RESULTS = Path(__file__).resolve().parent.parent / "experiment_results"


def append(name: str, row: dict) -> list[dict]:
    """Add one run to `name`.csv and hand back the whole history."""
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / f"{name}.csv"
    row = {"run_at": datetime.now().isoformat(timespec="seconds"), **row}
    existing = read(name)
    fields = list(row)
    for old in existing:                       # a later run may add columns
        for key in old:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in existing + [row]:
            writer.writerow({f: record.get(f, "") for f in fields})
    return existing + [row]


def read(name: str) -> list[dict]:
    path = RESULTS / f"{name}.csv"
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_detail(name: str, rows: list[dict]) -> None:
    """The per-step working for the latest run, overwritten each time.

    Kept because a summary row cannot show you *which* sentence was passed
    over, and that is what tells you whether the ranking rule is right.
    """
    if not rows:
        return
    RESULTS.mkdir(exist_ok=True)
    with (RESULTS / f"{name}.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def trend(history: list[dict], column: str) -> str:
    """`0.74 → 0.81 (+0.07)` across runs, or just the value if there is one."""
    values = [r.get(column) for r in history if r.get(column) not in (None, "")]
    if not values:
        return "—"
    try:
        numbers = [float(v) for v in values]
    except ValueError:
        return str(values[-1])
    if len(numbers) == 1:
        return f"{numbers[-1]:g}"
    change = numbers[-1] - numbers[0]
    return f"{numbers[0]:g} → {numbers[-1]:g} ({change:+g})"
