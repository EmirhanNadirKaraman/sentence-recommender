"""Experiment 5 — are the corpus pass's quality questions calibrated?

The four sentence questions of `corpus/questions.py` (`stands_alone`,
`complete`, `standard`, `well_formed`) each replace a rule, and the rules
have already judged thousands of sentences. So the slice is built from what
the rules flagged, plus a control the rules passed, and each question is
read against the rule it stands in for:

  no-verb flagged   `parser` verdict 0.4      complete       mostly no
  unbound flagged   `quality.unbound` > 0     stands_alone   mostly no
  dialect marks     `dialect` verdict         standard       low
  model refusals    `model` verdict 0.0       well_formed    mixed
  strange names     `parser` verdict 0.8      well_formed    yes — names are given
  clean control     no verdict, well formed   all four       high

A rule is not gold, so what comes out is agreement and a list of the
disagreements to read, not an accuracy. `expression` rides along unscored,
to be read. Subtitle text only: the transcripts are somebody's material and
do not leave the machine.

Runs one request per sentence with every sentence question in it, which is
the shape the pass will use; nothing here runs without a go.
"""
from __future__ import annotations

import random
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from corpus import questions                                # noqa: E402
from corpus.quality import unbound, well_formed             # noqa: E402
from db import Database                                     # noqa: E402
from experiments import results                             # noqa: E402

SLICE = "05-corpus-pass-slice"
REPORT = "05-are-the-quality-questions-calibrated.md"
SEED = 5

GROUPS = {
    "no_verb": ("complete", "no"),
    "unbound": ("stands_alone", "no"),
    "dialect": ("standard", "no"),
    "refused": ("well_formed", "mixed"),
    "strange_name": ("well_formed", "yes"),
    "control": ("all", "yes"),
}


def draw(app) -> list[dict]:
    """The slice, each row with its group and what the rule said."""
    random.seed(SEED)
    with Database(app.settings.own) as db:
        subtitle = {t for (t,) in db.rows(
            "SELECT text FROM corpus_sentence WHERE build = 'subtitle' AND teachable"
            " AND (language IS NULL OR language = 'de')")}
    con = sqlite3.connect(app.settings.state_path)
    marked = defaultdict(list)
    for text, verdict, source in con.execute(
            "SELECT text, verdict, source FROM sentence_verdict"):
        if text in subtitle:
            marked[(source, round(verdict, 2))].append(text)
    con.close()
    rows: list[dict] = []

    def take(texts: list[str], n: int, group: str, said: str) -> None:
        for text in random.sample(texts, min(n, len(texts))):
            rows.append({"group": group, "rule": said, "text": text})

    take(marked[("parser", 0.4)], 100, "no_verb", "no finite verb")
    take(marked[("dialect", 0.5)], 200, "dialect", "dialect")
    take(marked[("model", 0.0)], 200, "refused", "gloss refused")
    take(marked[("parser", 0.8)], 50, "strange_name", "strange name")
    judged = {t for texts in marked.values() for t in texts}
    clean = [t for t in random.sample(sorted(subtitle), 4000) if t not in judged]
    flagged = [t for t in clean if unbound(t) > 0][:100]
    passed = [t for t in clean if unbound(t) == 0 and well_formed(t)][:100]
    take(flagged, 100, "unbound", f"unbound pronoun")
    take(passed, 100, "control", "passed every rule")
    for n, row in enumerate(rows, 1):
        row["n"] = n
    return rows


def ask(rows: list[dict], on_progress=None) -> list[dict]:
    """Every sentence question of the pass, one request per sentence."""
    from typesafe_sdk import Noul, TypeSafeClient        # noqa: PLC0415
    from config import load_dotenv                       # noqa: PLC0415
    load_dotenv()
    asked = {key: Noul(instructions=q["instructions"], criteria=q["criteria"])
             for key, q in questions.SENTENCE.items()}
    out = []
    with TypeSafeClient() as client:
        for i, row in enumerate(rows, 1):
            state = questions.state_for(row["text"], {})
            started = time.time()
            response = client.system_one(state, asked)
            answer = {key: round(response.answers[key].noul, 3) for key in asked}
            out.append({**row, **answer, "model": response.model,
                        "input_tokens": response.usage.input_tokens,
                        "seconds": round(time.time() - started, 2)})
            if on_progress and (i % 50 == 0 or i == len(rows)):
                on_progress(i, len(rows))
    return out


def report(rows: list[dict]) -> None:
    lines = ["# Are the quality questions calibrated?", "",
             f"Numbers from `{SLICE}.csv`: {len(rows)} subtitle sentences, one request "
             "each carrying every sentence question of the corpus pass "
             f"(`corpus/questions.py`, version {questions.VERSION}). Each group is read "
             "against the rule that put it there; a rule is not gold, so this is agreement, "
             "and the disagreements are listed to be read.", "",
             "| group | rule says | n | question | median p | p ≥ 0.5 | p ≥ 0.9 | p ≤ 0.1 |",
             "|---|---|---|---|---|---|---|---|"]
    by_group = defaultdict(list)
    for r in rows:
        by_group[r["group"]].append(r)
    for group, (question, expect) in GROUPS.items():
        part = by_group.get(group, [])
        if not part:
            continue
        keys = list(questions.SENTENCE) if question == "all" else [question]
        keys = [k for k in keys if k != "expression"]
        for key in keys:
            ps = sorted(float(r[key]) for r in part)
            median = ps[len(ps) // 2]
            lines.append(f"| {group} | {part[0]['rule']} → expect {expect} | {len(part)} | "
                         f"`{key}` | {median:.2f} | {sum(p >= 0.5 for p in ps)} | "
                         f"{sum(p >= 0.9 for p in ps)} | {sum(p <= 0.1 for p in ps)} |")
    tokens = sum(int(r["input_tokens"]) for r in rows)
    seconds = sum(float(r["seconds"]) for r in rows)
    lines += ["", f"{tokens:,} input tokens, {seconds:.0f} s, model {rows[0]['model']}.", ""]
    lines += ["## Disagreements to read", ""]
    for group, (question, expect) in GROUPS.items():
        part = by_group.get(group, [])
        if not part or question == "all":
            continue
        if expect == "no":
            odd = sorted(part, key=lambda r: -float(r[question]))
            odd = [r for r in odd if float(r[question]) >= 0.7][:8]
            lines += [f"**{group}** — the rule said no, the judge says yes (p ≥ 0.7):", ""]
        elif expect == "yes":
            odd = sorted(part, key=lambda r: float(r[question]))
            odd = [r for r in odd if float(r[question]) <= 0.3][:8]
            lines += [f"**{group}** — the rule said the sentence is fine, the judge doubts it (p ≤ 0.3):", ""]
        else:
            odd = sorted(part, key=lambda r: float(r[question]))[:4] + \
                sorted(part, key=lambda r: -float(r[question]))[:4]
            lines += [f"**{group}** — the four the judge rejects most and the four it accepts most:", ""]
        for r in odd:
            lines.append(f"- {float(r[question]):.2f} — {r['text']}")
        lines.append("")
    control = by_group.get("control", [])
    if control:
        lines += ["**control** — passed every rule; the judge's lowest on each question:", ""]
        for key in questions.SENTENCE:
            worst = min(control, key=lambda r: float(r[key]))
            lines.append(f"- `{key}` {float(worst[key]):.2f} — {worst['text']}")
        lines.append("")
    lines += ["## `expression`, unscored", "",
              "The ten sentences the judge is surest contain a fixed expression, "
              "and the ten it is surest do not:", ""]
    for r in sorted(rows, key=lambda r: -float(r["expression"]))[:10]:
        lines.append(f"- {float(r['expression']):.2f} — {r['text']}")
    lines.append("")
    for r in sorted(rows, key=lambda r: float(r["expression"]))[:10]:
        lines.append(f"- {float(r['expression']):.2f} — {r['text']}")
    (results.RESULTS / REPORT).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  wrote experiment_results/{REPORT}")


def main() -> None:
    from context import Application                      # noqa: PLC0415
    app = Application()
    what = sys.argv[1] if len(sys.argv) > 1 else "draw"
    if what == "draw":
        rows = draw(app)
        results.write_detail(SLICE, rows)
        from collections import Counter                  # noqa: PLC0415
        print(f"  wrote experiment_results/{SLICE}.csv —", dict(Counter(r["group"] for r in rows)))
    elif what == "ask":
        rows = results.read(SLICE)
        if not rows:
            raise SystemExit("draw first")
        if "well_formed" in rows[0]:
            raise SystemExit("already asked; delete the slice to ask again")
        answered = ask(rows, lambda i, n: print(f"  asked {i}/{n}", flush=True))
        results.write_detail(SLICE, answered)
        report(answered)
    elif what == "report":
        report(results.read(SLICE))
    else:
        raise SystemExit("usage: corpus_pass.py [draw|ask|report]")


if __name__ == "__main__":
    main()
