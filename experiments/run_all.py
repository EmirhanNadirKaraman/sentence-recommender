"""Run every experiment, record the numbers, and write up what they mean.

Each run appends a row to a CSV in `experiment_results/` and rewrites the
report from the whole file. The corpus grows as channels are added, so a
single measurement says little; the history says whether the examples the
roadmap shows are getting better.
"""
from __future__ import annotations

import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from context import Application                          # noqa: E402
from experiments import example_choice, quality_closure, results  # noqa: E402
from corpus.quality import BAND, IDEAL, VERSION      # noqa: E402


def main() -> None:
    app = Application()
    sentences = len(app.corpus("subtitle", list_only=True))

    rows = example_choice.run(app)
    results.write_detail("01-example-choice-detail", [
        {"step": i + 1, "candidates": r["candidates"],
         "well_formed": r["well_formed"], "chosen_score": round(r["chosen_score"], 3),
         "best_score": round(r["best_score"], 3), "chosen": r["chosen"],
         "best": r["best"]}
        for i, r in enumerate(rows)])
    lengths = sorted(len(r["chosen"].split()) for r in rows)
    modal = statistics.mode(lengths)
    history = results.append("01-example-choice", {
        "quality_version": VERSION,
        "sentences": sentences,
        "steps": len(rows),
        "steps_with_well_formed": sum(1 for r in rows if r["well_formed"]),
        "steps_single_candidate": sum(1 for r in rows if r["candidates"] == 1),
        "steps_improvable": sum(1 for r in rows if r["best_score"] > r["chosen_score"]),
        "median_candidates": statistics.median(r["candidates"] for r in rows),
        "mean_chosen_score": round(statistics.mean(r["chosen_score"] for r in rows), 3),
        "mean_best_score": round(statistics.mean(r["best_score"] for r in rows), 3),
        # A mean score cannot see clustering: every example landing on one
        # length scores perfectly and reads monotonously.
        "mean_example_words": round(statistics.mean(lengths), 2),
        "median_example_words": statistics.median(lengths),
        "modal_example_words": modal,
        "modal_share": round(lengths.count(modal) / len(lengths), 3),
    })
    _report_choice(history, rows)

    closure = quality_closure.run(app)
    everything, good = closure["all sentences"], closure["well-formed only"]
    lost = everything["reached"] - good["reached"]
    history = results.append("02-quality-closure", {
        "quality_version": VERSION,
        "all_sentences": everything["sentences"],
        "all_reached": everything["reached"],
        "well_formed_sentences": good["sentences"],
        "well_formed_reached": good["reached"],
        "present_units": closure["present_units"],
        "words_lost": lost,
        "share_lost": round(lost / max(everything["reached"], 1), 4),
    })
    _report_closure(history)


def _table(history: list[dict], columns: list[tuple[str, str]]) -> str:
    head = "| run | " + " | ".join(label for label, _ in columns) + " |\n"
    head += "|---" * (len(columns) + 1) + "|\n"
    for record in history[-8:]:
        cells = " | ".join(f"{record.get(key, ''):>}" for _, key in columns)
        head += f"| {record['run_at'][:16].replace('T', ' ')} | {cells} |\n"
    return head


def _write(name: str, body: str) -> None:
    (results.RESULTS / name).write_text(body, encoding="utf-8")
    print(f"  wrote experiment_results/{name}")


def _report_choice(history: list[dict], rows: list[dict]) -> None:
    last = history[-1]
    steps = int(last["steps"])
    share = int(last["steps_with_well_formed"]) / steps
    improvable = [r for r in rows if r["best_score"] > r["chosen_score"]]
    _write("01-are-better-examples-already-available.md", f"""\
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

Well-formed means {BAND[0]}-{BAND[1]} words in a single sentence, scored on a curve peaking
peaking at {IDEAL} words. It says nothing about meaning.

## History

{_table(history, [("sentences", "sentences"), ("steps", "steps"),
                  ("with a good candidate", "steps_with_well_formed"),
                  ("improvable", "steps_improvable"),
                  ("median candidates", "median_candidates"),
                  ("shown", "mean_chosen_score"), ("best", "mean_best_score"),
                  ("median words", "median_example_words"),
                  ("on one length", "modal_share"), ("scale", "quality_version")])}
Rows are comparable only within a `scale` — `corpus/quality.py` stamps its
version on every run, because a mean from one definition of quality says
nothing about a mean from another.

Shown vs best, across runs: **{results.trend(history, 'mean_chosen_score')}**
against **{results.trend(history, 'mean_best_score')}**. The gap between those
two is what a better ranking rule would close; `best` is the ceiling ranking
alone can reach, and it moves only when the corpus gains better sentences.

## What it means

{_verdict(share, int(last['steps_single_candidate']), steps)}

## What was passed over, this run

| step shows | it could have shown |
|---|---|
""" + "".join(f"| {r['chosen'][:56]} | {r['best'][:56]} |\n" for r in improvable[:10]))


def _report_closure(history: list[dict]) -> None:
    last = history[-1]
    share = float(last["share_lost"])
    _write("02-what-insisting-on-quality-costs.md", f"""\
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

{_table(history, [("all sentences", "all_sentences"), ("reached", "all_reached"),
                  ("well-formed", "well_formed_sentences"),
                  ("reached", "well_formed_reached"),
                  ("words lost", "words_lost"), ("share", "share_lost")])}
Words lost across runs: **{results.trend(history, 'words_lost')}**.

## What it means

{_closure_verdict(share)}

## A caveat on reading this

A single closure cannot see ordering. A word taught from a poor sentence in
the unrestricted walk is not necessarily lost in the restricted one — it may
arrive later, from better material, once other words are known. The figure
is therefore an upper bound on what restricting really costs.
""")


def _verdict(share: float, single: int, steps: int) -> str:
    if share > 0.7:
        return (f"**Rank, do not restrict.** {share:.0%} of steps already have a "
                "well-formed sentence among their candidates, so the picker is "
                "passing over material it already holds. A better ranking rule "
                "cannot cost a single word of coverage, because the candidates "
                f"per step are unchanged. Only {single:,} steps ({single / steps:.0%}) "
                "have one candidate, where no rule can help.")
    if share > 0.4:
        return (f"**Mixed.** {share:.0%} of steps have a well-formed candidate. "
                "Ranking helps those; the rest are limited by material.")
    return (f"**Material, not choice.** Only {share:.0%} of steps have a "
            "well-formed candidate. Either the corpus needs more material or "
            "the bar is too strict for spoken subtitles.")


def _closure_verdict(share: float) -> str:
    if share < 0.05:
        return (f"Restricting costs {share:.1%}. Cheap — but only worth paying if "
                "ranking has already been tried, since ranking costs nothing.")
    if share < 0.25:
        return f"Restricting costs {share:.1%}. Ranking is the better trade."
    return (f"Restricting costs {share:.1%}, too much. Quality belongs in the "
            "ranking, not in the walk.")


if __name__ == "__main__":
    main()
