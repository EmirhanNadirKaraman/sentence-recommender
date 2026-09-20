"""Experiment 4 — does the matcher's sentence carry the pattern?

The dictionary the matcher reads, `data/final_result.txt`, holds one
blueprint per verb: `stehen` is `jdm. (Dat) stehen` and nothing else. So a
pattern unit is the verb wearing that one label, and nothing has ever asked
whether the sentence realises the label — `Ich stehe auf der Rolltreppe`
carries `jdm. (Dat) stehen`, *to suit someone*, in 3,253 sentences of which
a dozen read by hand carried it in none.

Two defects, and they are not the same one. An auxiliary or a modal standing
in front of another verb — `habe … bestanden`, `kann … machen` — is
decidable from the parse and was the two most frequent patterns in the
corpus; `matcher.phrase_finder.carries_another_verb` now refuses those.
What is left is semantic: `es gibt` against *give someone something*,
`stehen` meaning stand or be written or be into, `der Fall` inside `auf
jeden Fall`. That half is what a model would be asked, and this experiment
is the benchmark for asking it: a labelled sample of pattern rows, split
into what the rule fixes and what it cannot.

Three parts, run separately because the middle one is a person:

  sample   draws the rows and writes them for judging — blind, without the
           rule column, so a label is a reading of the sentence rather than
           of the tag
  judge    is done by hand (or by a stronger reader) into the judged file
  measure  parses the sample again to tag what the rule catches, counts the
           rule's effect over a fresh slice of the corpus, and reports

The two model arms — TypeSafe's Jev and the local endpoint's yes/no
logprob — read the judged file and are not here yet: the first needs a key
and a decision about what may leave the machine, the second the plumbing in
TODO #26. What they will be scored on is fixed by this file.
"""
from __future__ import annotations

import csv
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import Database                                     # noqa: E402
from experiments import results                             # noqa: E402

SAMPLE = "04-pattern-sense-sample"
JUDGED = "04-pattern-sense-judged"
RULE = "04-pattern-sense-rule"
REPORT = "04-does-the-sentence-carry-the-pattern.md"

# Reproducible: the judged file is keyed on `n`, and a redraw that shuffled
# the rows would orphan every label.
SEED = 0.04
UNIFORM = 300          # rows drawn uniformly — what the corpus suffers
PANEL_PATTERNS = 50    # the heaviest patterns, three rows each — what the
PANEL_EACH = 3         # dictionary suffers, pattern by pattern

# What the parse says about a row. `aux` and `modal` are what the matcher
# now refuses; `es_gibt` is the expletive it now routes to its own unit;
# blank is the semantic residue.
RULES = ("aux", "modal", "es_gibt", "")


# --- sample ---------------------------------------------------------------

def sample(app) -> list[dict]:
    """Draw the rows to judge and write them, blind, to the sample file."""
    rows: list[dict] = []
    with Database(app.settings.own) as db:
        db.rows("SELECT setseed(%s)", (SEED,))
        for stratum, drawn in (("uniform", _uniform(db)), ("panel", _panel(db))):
            for pattern, surface, text, video, start in drawn:
                rows.append({"stratum": stratum, "pattern": pattern,
                             "surface": surface or "", "text": text,
                             "video": video or "", "start": start or ""})
    glosses = _glosses(app, {r["pattern"] for r in rows})
    for n, row in enumerate(rows, 1):
        row["n"] = n
        row["gloss"] = glosses.get(row["pattern"], "")
    ordered = [{"n": r["n"], "stratum": r["stratum"], "pattern": r["pattern"],
                "gloss": r["gloss"], "surface": r["surface"], "text": r["text"],
                "video": r["video"], "start": r["start"]} for r in rows]
    results.write_detail(SAMPLE, ordered)
    return ordered


_ROW = ("SELECT u.key, u.surface, s.text, s.video_id, s.start_time"
        " FROM corpus_unit u JOIN corpus_sentence s ON s.id = u.sentence_id"
        " WHERE u.kind = 'pattern' AND s.build = 'subtitle' AND s.teachable"
        " AND (s.language IS NULL OR s.language = 'de')")


def _uniform(db) -> list[tuple]:
    """Rows in proportion to their frequency: `haben` gets its share."""
    return db.rows(_ROW + " ORDER BY random() LIMIT %s", (UNIFORM,))


def _panel(db) -> list[tuple]:
    """A few rows from each of the heaviest patterns, so the per-pattern
    view is not one row wide."""
    top = db.rows(
        "SELECT u.key FROM corpus_unit u JOIN corpus_sentence s"
        " ON s.id = u.sentence_id WHERE u.kind = 'pattern'"
        " AND s.build = 'subtitle' AND s.teachable"
        " GROUP BY u.key ORDER BY count(*) DESC LIMIT %s", (PANEL_PATTERNS,))
    out: list[tuple] = []
    for (key,) in top:
        out.extend(db.rows(_ROW + " AND u.key = %s ORDER BY random() LIMIT %s",
                           (key, PANEL_EACH)))
    return out


def _glosses(app, patterns: set[str]) -> dict[str, str]:
    """The sense the deck's gloss most often gave each pattern.

    The local model's reading, not a dictionary's — and for a collapsed
    pattern it is one of several, which is part of what the labels will
    show. It is on the sheet so the judge knows what the label claims,
    not as the answer.
    """
    con = sqlite3.connect(app.settings.state_path)
    out: dict[str, str] = {}
    for key in patterns:
        row = con.execute(
            "SELECT means FROM unit_sense WHERE kind = 'pattern' AND key = ?"
            " AND means IS NOT NULL GROUP BY means ORDER BY count(*) DESC"
            " LIMIT 1", (key,)).fetchone()
        if row:
            out[key] = row[0]
    con.close()
    return out


# --- measure ----------------------------------------------------------------

def rule_for(doc, pattern: str, finder) -> str:
    """What the parse says about the token that gave `pattern` to this
    sentence, or blank when nothing mechanical does.

    The row was stored before `carries_another_verb` existed, so the token is
    found the way the old matcher found it: any verb whose bare lemma looks
    the blueprint up. A separable prefix is not folded in — an auxiliary
    has none, and a full verb is not what this is looking for.
    """
    for token in doc:
        if token.pos_ not in ("VERB", "AUX"):
            continue
        lemma = token.lemma_.lower()
        if finder.verb_blueprint_map.get(lemma) != pattern:
            continue
        if finder.expletive_construction(token) is not None:
            return "es_gibt"
        if finder.carries_another_verb(token):
            return "modal" if token.tag_.startswith("VM") else "aux"
    return ""


def tag_rules(app, rows: list[dict]) -> list[dict]:
    """The rule column, joined onto judged rows after the judging."""
    finder = app.analyzer.matcher
    docs = finder.nlp.pipe([r["text"] for r in rows], batch_size=64)
    for row, doc in zip(rows, docs):
        row["rule"] = rule_for(doc, row["pattern"], finder)
    return rows


def rule_effect(app, n: int = 10_000) -> dict:
    """How many pattern rows the rule refuses, over a fresh slice.

    Counted by re-deriving what the old matcher would have emitted — every
    verb token's blueprint — and asking the rule about each, so it needs no
    rebuild and no old copy of the code. Only registered, trustworthy
    patterns count, since those are the only ones that ever became units.
    """
    from corpus.analyzer import UnitAnalyzer             # noqa: PLC0415
    analyzer = app.analyzer
    finder = analyzer.matcher
    with Database(app.settings.own) as db:
        db.rows("SELECT setseed(%s)", (SEED,))
        texts = [t for (t,) in db.rows(
            "SELECT text FROM corpus_sentence WHERE build = 'subtitle'"
            " AND teachable AND (language IS NULL OR language = 'de')"
            " ORDER BY random() LIMIT %s", (n,))]
    emitted: Counter[str] = Counter()
    refused: Counter[str] = Counter()
    rerouted: Counter[str] = Counter()
    by_rule: Counter[str] = Counter()
    for doc in finder.nlp.pipe(texts, batch_size=500,
                               n_process=app.settings.analysis_processes):
        for token in doc:
            if token.pos_ not in ("VERB", "AUX") or token.dep_ == "aux":
                continue
            prefix = "".join(c.lemma_.lower() for c in token.children
                             if c.dep_ == "svp")
            entry = finder.verb_blueprint_map.get(prefix + token.lemma_.lower())
            if entry is None or entry not in analyzer._patterns:
                continue
            phrase = {"match_type": "exact", "indices": [token.i]}
            if not UnitAnalyzer._trustworthy(phrase, doc):
                continue
            if finder.carries_another_verb(token):
                refused[entry] += 1
                by_rule["modal" if token.tag_.startswith("VM") else "aux"] += 1
            elif finder.expletive_construction(token) is not None:
                rerouted[entry] += 1
                by_rule["es_gibt"] += 1
            else:
                emitted[entry] += 1
    total = sum(emitted.values()) + sum(refused.values()) + sum(rerouted.values())
    keys = set(emitted) | set(refused) | set(rerouted)
    before = {k: emitted[k] + refused[k] + rerouted[k] for k in keys}
    detail = [{"pattern": key, "before": before[key],
               "refused": refused[key], "rerouted": rerouted[key],
               "share_refused": round(refused[key] / before[key], 3),
               "share_rerouted": round(rerouted[key] / before[key], 3)}
              for key in sorted(keys, key=lambda k: -before[k])]
    results.write_detail(RULE, detail)
    return {"sentences": len(texts), "verb_pattern_rows": total,
            "refused": sum(refused.values()), "aux": by_rule["aux"],
            "modal": by_rule["modal"], "rerouted": sum(rerouted.values()),
            "share_refused": round(sum(refused.values()) / max(total, 1), 4),
            "detail": detail}


# --- report -----------------------------------------------------------------

def judged() -> list[dict]:
    return results.read(JUDGED)


def summarise(rows: list[dict]) -> dict:
    """The numbers the report is written from, per stratum and per rule."""
    out: dict = {}
    for stratum in ("uniform", "panel"):
        part = [r for r in rows if r["stratum"] == stratum]
        verdicts = Counter(r["verdict"] for r in part)
        rules = Counter(r["rule"] for r in part)
        out[stratum] = {"rows": len(part), "verdicts": verdicts, "rules": rules}
        # The rule's own precision: of the rows it tags, how many the judge
        # also called something other than the frame.
        tagged = [r for r in part if r["rule"]]
        out[stratum]["rule_agreed"] = sum(1 for r in tagged if r["verdict"] != "frame")
        residue = [r for r in part if not r["rule"]]
        out[stratum]["residue"] = Counter(r["verdict"] for r in residue)
    per_pattern: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        if r["stratum"] == "panel":
            per_pattern[r["pattern"]][r["verdict"]] += 1
    out["per_pattern"] = per_pattern
    return out


def write_report(rows: list[dict], effect: dict | None) -> None:
    s = summarise(rows)
    lines = ["# Does the sentence carry the pattern?", ""]
    lines += [
        "Numbers from `04-pattern-sense-judged.csv`, every row read by hand "
        "against the sentence; the rule column joined afterwards from a fresh "
        "parse. `04-pattern-sense-rule.csv` is the rule's effect over a fresh "
        "slice of the corpus. The two model arms are not run yet.", ""]
    lines += ["## What this tests", "",
              "A pattern unit is the verb wearing the one blueprint the "
              "dictionary holds for it. This asks how often the sentence "
              "realises that blueprint, and how much of the rest a parse "
              "rule already catches.", "",
              "The labelling rule, so a second judge can reproduce it: "
              "*frame* when the word is in the blueprint's sense and any "
              "slot it lacks is one the frame lets you drop (`sagen` with no "
              "recipient, `passieren` with no dative, `helfen` with no "
              "object); *other* when the missing slot is the one that carries "
              "the sense (`sterben` without `an`, `fliehen` without `vor`, "
              "`aussehen` without `nach`), or the word is in another sense or "
              "frame altogether (an auxiliary, a modal, `glauben` with a "
              "clause, `bedeuten` meaning signify); *construction* when the "
              "tokens belong to a multiword unit the dictionary does not list "
              "(`es gibt`, `auf jeden Fall`, `eine Rolle spielen`), whether or "
              "not the word's own sense is still visible inside it; *unclear* "
              "when the subtitle is too garbled to tell.", ""]
    for stratum, title in (("uniform", "Uniform over rows — what the corpus suffers"),
                           ("panel", "Panel of the heaviest patterns — what the dictionary suffers")):
        part = s[stratum]
        v = part["verdicts"]
        lines += [f"## {title}", "",
                  f"{part['rows']} rows.", "",
                  "| verdict | rows | share |", "|---|---|---|"]
        for verdict in ("frame", "other", "construction", "unclear"):
            lines.append(f"| {verdict} | {v[verdict]} | {v[verdict] / part['rows']:.0%} |")
        lines += ["", "| rule | rows | judge agreed |", "|---|---|---|"]
        for rule in ("aux", "modal", "es_gibt"):
            tagged = [r for r in rows if r["stratum"] == stratum and r["rule"] == rule]
            agreed = sum(1 for r in tagged if r["verdict"] != "frame")
            lines.append(f"| {rule} | {len(tagged)} | {agreed} |")
        res = part["residue"]
        n_res = sum(res.values())
        lines += ["", f"Residue after the rule: {n_res} rows, of which "
                  f"{res['frame']} carry the frame ({res['frame'] / max(n_res, 1):.0%}), "
                  f"{res['other']} another sense of the same word, "
                  f"{res['construction']} a construction the dictionary lacks, "
                  f"{res['unclear']} unclear.", ""]
    lines += ["## Per pattern, on the panel", "",
              "| pattern | frame | other | construction | unclear |", "|---|---|---|---|---|"]
    for pattern, c in sorted(s["per_pattern"].items(), key=lambda kv: -sum(kv[1].values())):
        lines.append(f"| `{pattern}` | {c['frame']} | {c['other']} | {c['construction']} | {c['unclear']} |")
    if effect:
        lines += ["", "## What the rule refuses, over a fresh slice", "",
                  f"{effect['sentences']:,} sentences, {effect['verb_pattern_rows']:,} "
                  f"verb pattern rows the old matcher would have emitted; the rule "
                  f"refuses {effect['refused']:,} ({effect['share_refused']:.1%}) — "
                  f"{effect['aux']:,} auxiliaries, {effect['modal']:,} modals — and "
                  f"routes {effect['rerouted']:,} more to `es gibt`.", "",
                  "An estimate, not the rebuild: the rows are re-derived here by "
                  "looking each verb token's lemma up, which is the matcher's "
                  "exact path but not its fuzzy fallback or its multi-token "
                  "phrase. The number the corpus will actually lose is one query "
                  "after `build-corpus subtitle` — `count(*)` of pattern rows "
                  "against the 603,624 there today.", "",
                  "| pattern | rows | refused | rerouted |", "|---|---|---|---|"]
        for d in effect["detail"][:20]:
            lines.append(f"| `{d['pattern']}` | {d['before']} | {d['refused']} "
                         f"({d['share_refused']:.0%}) | {d['rerouted']} ({d['share_rerouted']:.0%}) |")
    lines += ["", "## Constructions the labels named", "",
              "What the sentence carried instead, where the judge named it — "
              "the candidates a discovery pass would have to propose:", ""]
    named = Counter(r["what"] for r in rows if r["verdict"] == "construction" and r["what"])
    for what, n in named.most_common():
        lines.append(f"- `{what}` × {n}")
    (results.RESULTS / REPORT).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  wrote experiment_results/{REPORT}")


def main() -> None:
    from context import Application                      # noqa: PLC0415
    app = Application()
    what = sys.argv[1] if len(sys.argv) > 1 else "sample"
    if what == "sample":
        rows = sample(app)
        print(f"  wrote experiment_results/{SAMPLE}.csv — {len(rows)} rows to judge")
    elif what == "measure":
        rows = judged()
        if not rows:
            raise SystemExit(f"nothing judged yet in experiment_results/{JUDGED}.csv")
        rows = tag_rules(app, rows)
        with (results.RESULTS / f"{JUDGED}.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        effect = rule_effect(app)
        print(f"  rule refuses {effect['refused']:,} of {effect['verb_pattern_rows']:,} "
              f"verb pattern rows ({effect['share_refused']:.1%}) over {effect['sentences']:,} sentences")
        write_report(rows, effect)
    else:
        raise SystemExit("usage: pattern_sense.py [sample|measure]")


if __name__ == "__main__":
    main()
