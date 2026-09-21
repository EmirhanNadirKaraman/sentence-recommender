"""Experiment 6 — is a cheaper `level` question the same question?

The corpus pass asks `level` inside a request that carries every other
question, about 1,630 input tokens a sentence, most of them the questions'
own text. Levelling the rest of the subtitle corpus that way is ~$15, and
what the reel needs from it is the level alone. Two cheaper forms:

  A  one sentence per request, the `level` question exactly as the pass
     asks it, nothing else in the state -- ~480 tokens a sentence
  B  twenty sentences per request, the A1–C1 descriptions once in the
     state as `scale`, and twenty short Choice questions pointing at it,
     criteria reduced to the bare labels -- ~85 tokens a sentence

A changes the surroundings only; B changes the question. Both are put to
200 sentences the pass has already answered, stratified by the level it
gave, and read against those answers: exact and within-one agreement of
the top label, the mean shift in expected level, and the cost. Subtitle
text only, and nothing here runs without a go.
"""
from __future__ import annotations

import json
import random
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from corpus.questions import LEVEL, LEVELS, VERSION            # noqa: E402
from experiments import results                                 # noqa: E402

SAMPLE = "06-level-forms-sample"
DETAIL = "06-level-forms"
REPORT = "06-is-a-cheaper-level-question-the-same-question.md"
SEED = 6
PER_LEVEL = 40
BATCH = 20
PER_MILLION = 0.042

BATCHED = ("At which CEFR level, as `scale` describes them, could a learner "
           "read `sentences.{id}` comfortably?")


def expected(probabilities: dict[str, float]) -> float:
    """The expected level as a number of levels above A1, 0–4."""
    return sum(probabilities.get(label, 0.0) * i for i, label in enumerate(LEVELS))


def draw(app) -> list[dict]:
    """200 sentences the pass has levelled, up to 40 per top label."""
    random.seed(SEED)
    con = sqlite3.connect(app.settings.state_path)
    by_level: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for text, distribution in con.execute(
            "SELECT text, distribution FROM sentence_answer"
            " WHERE question = 'level' AND version = ? AND model = ?",
            (VERSION, app.settings.judge_model)):
        dist = json.loads(distribution)
        by_level[max(dist, key=dist.get)].append((text, dist))
    con.close()
    rows: list[dict] = []
    for label in LEVELS:
        pool = by_level.get(label, [])
        for text, dist in random.sample(pool, min(PER_LEVEL, len(pool))):
            rows.append({"text": text, "stored_top": label,
                         "stored_expected": round(expected(dist), 3),
                         "stored": json.dumps(dist, ensure_ascii=False)})
    short = PER_LEVEL * len(LEVELS) - len(rows)
    if short > 0:
        taken = {r["text"] for r in rows}
        rest = [(t, d, lab) for lab, pool in by_level.items() for t, d in pool
                if t not in taken]
        for text, dist, label in random.sample(rest, min(short, len(rest))):
            rows.append({"text": text, "stored_top": label,
                         "stored_expected": round(expected(dist), 3),
                         "stored": json.dumps(dist, ensure_ascii=False)})
    random.shuffle(rows)
    for n, row in enumerate(rows, 1):
        row["n"] = n
    return rows


def ask(rows: list[dict], model: str, on_progress=None) -> list[dict]:
    from typesafe_sdk import Choice, RetryPolicy, TypeSafeClient  # noqa: PLC0415
    from config import load_dotenv                                # noqa: PLC0415
    load_dotenv()
    out = [dict(r) for r in rows]
    with TypeSafeClient(model=model, retry=RetryPolicy(max_retries=4, timeout=60.0)) as client:
        # A: the pass's question, alone.
        alone = Choice(instructions=LEVEL["instructions"], criteria=LEVEL["criteria"])
        for i, row in enumerate(out, 1):
            response = client.system_one({"sentence": row["text"]}, {"level": alone})
            answer = response.answers["level"]
            row.update(a_top=answer.choice,
                       a_expected=round(expected(dict(answer.probabilities)), 3),
                       a=json.dumps(dict(answer.probabilities), ensure_ascii=False),
                       a_tokens=response.usage.input_tokens)
            if on_progress and (i % 50 == 0 or i == len(out)):
                on_progress("A", i, len(out))
        # B: twenty at once, the scale in the state.
        labels = {label: label for label in LEVELS}
        for start in range(0, len(out), BATCH):
            batch = out[start:start + BATCH]
            state = {"scale": LEVEL["criteria"],
                     "sentences": {f"s{i}": row["text"] for i, row in enumerate(batch, 1)}}
            asked = {f"s{i}": Choice(instructions=BATCHED.format(id=f"s{i}"), criteria=labels)
                     for i in range(1, len(batch) + 1)}
            response = client.system_one(state, asked)
            share = response.usage.input_tokens / len(batch)
            for i, row in enumerate(batch, 1):
                answer = response.answers[f"s{i}"]
                row.update(b_top=answer.choice,
                           b_expected=round(expected(dict(answer.probabilities)), 3),
                           b=json.dumps(dict(answer.probabilities), ensure_ascii=False),
                           b_tokens=round(share, 1))
            if on_progress:
                on_progress("B", start + len(batch), len(out))
        model_said = response.model
    for row in out:
        row["model"] = model_said
    return out


def report(rows: list[dict]) -> None:
    lines = ["# Is a cheaper `level` question the same question?", "",
             f"Numbers from `{DETAIL}.csv`: {len(rows)} subtitle sentences the corpus pass "
             f"had levelled (question version {VERSION}, model {rows[0]['model']}), "
             "stratified by the level it gave, asked again two cheaper ways. "
             "A is the same question alone in the request; B is twenty sentences a "
             "request with the level descriptions in the state and bare labels as the "
             "criteria. Read against the pass's answers.", "",
             "| form | tokens/sentence | $ per 1,000 | top label agrees | within one level | "
             "mean shift (levels) | mean abs. difference (levels) |",
             "|---|---|---|---|---|---|---|"]
    for form in ("a", "b"):
        n = len(rows)
        tokens = sum(float(r[f"{form}_tokens"]) for r in rows) / n
        exact = sum(r[f"{form}_top"] == r["stored_top"] for r in rows) / n
        near = sum(abs(LEVELS.index(r[f"{form}_top"]) - LEVELS.index(r["stored_top"])) <= 1
                   for r in rows) / n
        diffs = [float(r[f"{form}_expected"]) - float(r["stored_expected"]) for r in rows]
        shift = sum(diffs) / n
        absd = sum(abs(d) for d in diffs) / n
        lines.append(f"| {form.upper()} | {tokens:,.0f} | {tokens / 1e6 * PER_MILLION * 1000:.3f} | "
                     f"{exact:.0%} | {near:.0%} | {shift:+.2f} | {absd:.2f} |")
    lines += ["", "The pass's own answers are not gold; they are the same model with more "
              "in front of it. Agreement here says whether the cheaper form is *that* "
              "question, which is what a video's level averaged from it will inherit.", ""]
    for form in ("a", "b"):
        lines += [f"## Form {form.upper()}: the pass's top label (rows) against the form's (columns)", "",
                  "| pass \\ form | " + " | ".join(LEVELS) + " |",
                  "|---|" + "---|" * len(LEVELS)]
        grid = Counter((r["stored_top"], r[f"{form}_top"]) for r in rows)
        for stored in LEVELS:
            if not any(grid[(stored, f)] for f in LEVELS):
                continue
            lines.append(f"| {stored} | " + " | ".join(str(grid[(stored, f)]) for f in LEVELS) + " |")
        lines.append("")
    lines += ["## The sentences the forms move most", ""]
    for form in ("a", "b"):
        moved = sorted(rows, key=lambda r: -abs(float(r[f"{form}_expected"]) - float(r["stored_expected"])))[:6]
        lines.append(f"**{form.upper()}**:")
        lines.append("")
        for r in moved:
            lines.append(f"- pass {r['stored_top']} ({float(r['stored_expected']):.2f}) → "
                         f"{r[f'{form}_top']} ({float(r[f'{form}_expected']):.2f}) — {r['text']}")
        lines.append("")
    (results.RESULTS / REPORT).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  wrote experiment_results/{REPORT}")


def main() -> None:
    from context import Application                      # noqa: PLC0415
    app = Application()
    what = sys.argv[1] if len(sys.argv) > 1 else "draw"
    if what == "draw":
        rows = draw(app)
        results.write_detail(SAMPLE, rows)
        print(f"  wrote experiment_results/{SAMPLE}.csv —",
              dict(Counter(r["stored_top"] for r in rows)))
    elif what == "ask":
        rows = results.read(SAMPLE)
        if not rows:
            raise SystemExit("draw first")
        if results.read(DETAIL):
            raise SystemExit(f"already asked; delete {DETAIL}.csv to ask again")
        answered = ask(rows, app.settings.judge_model,
                       lambda form, i, n: print(f"  {form} {i}/{n}", flush=True))
        results.write_detail(DETAIL, answered)
        tokens = sum(float(r["a_tokens"]) + float(r["b_tokens"]) for r in answered)
        print(f"  {tokens:,.0f} input tokens · ${tokens / 1e6 * PER_MILLION:.3f}")
        report(answered)
    elif what == "report":
        report(results.read(DETAIL))
    else:
        raise SystemExit("usage: level_forms.py [draw|ask|report]")


if __name__ == "__main__":
    main()
