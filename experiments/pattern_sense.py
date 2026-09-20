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
HISTORY = "04-pattern-sense"             # one row per `measure`, as the others keep
ARM = "04-pattern-sense-arm-{}"          # one file per judge: jev, local
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


def _last_effect() -> dict | None:
    """The rule's effect as the last `measure` left it, for a report written
    by an arm run that did not re-parse the corpus."""
    history = results.read(HISTORY)
    if not history:
        return None
    last = {k: (float(v) if k == "share_refused" else int(v))
            for k, v in history[-1].items()
            if k in ("sentences", "verb_pattern_rows", "refused", "aux", "modal",
                     "rerouted", "share_refused")}
    detail = results.read(RULE)
    for d in detail:
        for k in ("before", "refused", "rerouted"):
            d[k] = int(d[k])
        for k in ("share_refused", "share_rerouted"):
            d[k] = float(d[k])
    return {**last, "detail": detail}


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
    for name in ARMS:
        for asking in QUESTIONS:
            lines += [""] + arm_section(name, asking)
    lines += ["", "## Constructions the labels named", "",
              "What the sentence carried instead, where the judge named it — "
              "the candidates a discovery pass would have to propose:", ""]
    named = Counter(r["what"] for r in rows if r["verdict"] == "construction" and r["what"])
    for what, n in named.most_common():
        lines.append(f"- `{what}` × {n}")
    (results.RESULTS / REPORT).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  wrote experiment_results/{REPORT}")


# --- the arms ---------------------------------------------------------------
#
# Two judges asked the labelling rule's own question, one row per request,
# and scored against the judged file. Neither is told the English of the
# unit: the deck's gloss would have said `gehört means heard` for
# `jdm. (Dat) gehören` and `auf jeden Fall means definitely` for `der Fall`,
# and a judge fed that answers the gloss's question rather than the
# label's. What both get is the canonical, its spoken form, and the one-line
# legend for the notation; reading the German is the thing under test.

NOTATION = ("In a canonical, `jdm.`/`jemandem` is a person in the dative and "
            "`jdn.`/`jemanden` a person in the accusative, `etw.`/`etwas` a "
            "thing, `(Dat)`/`(Akk)` its case, `sich` a reflexive; a "
            "preposition written before them belongs to the frame; an article "
            "with a noun is that noun in its ordinary sense; a comma separates "
            "two spellings of one word.")

QUESTION = ("Do the marked words in `sentence` use the unit `unit.spoken` "
            "(canonical `unit.canonical`) in the sense and frame that "
            "canonical names? Yes if the word is used in that sense, even "
            "with a slot left unsaid — a recipient or an object the speaker "
            "omitted. No if the word is an auxiliary or a modal standing in "
            "front of another verb, is used in another sense or with another "
            "frame (a different preposition, a reflexive, a clause where the "
            "frame names a person or a thing), or belongs to a fixed "
            "multiword expression the unit does not name.")

CRITERIA = {
    "true": ("The marked words realise the canonical unit's own sense and "
             "frame here. Inflection and separated parts are allowed, and a "
             "slot left unsaid still counts."),
    "false": ("An auxiliary or modal use, another sense or frame of the same "
              "word, or a fixed expression the canonical does not name — "
              "`Bescheid wissen` is not `etwas wissen`, `sich ändern` is not "
              "`etwas ändern`."),
}

# B's question (TODO #26, decided 2026-09-20): the goal is the word, not
# the frame, so what a card must keep off its examples is narrower — a
# fixed expression with a meaning of its own, or a different word wearing
# the same letters. Any ordinary sense or frame of the word itself, an
# auxiliary or a modal included, is a fair example of the word.
QUESTION_PLAIN = (
    "Are the marked words in `sentence` the word `unit.spoken` itself, in "
    "any of its ordinary senses or frames? Yes if it is that word used as "
    "itself — any sense, any preposition or case it takes here, reflexive "
    "or not, as an auxiliary or a modal — even with a slot left unsaid. No "
    "if the marked words belong to a fixed multiword expression whose "
    "meaning is not the word's own, or if they are a different word that "
    "happens to look the same (a participle of another verb, an adjective, "
    "a name).")

CRITERIA_PLAIN = {
    "true": ("The word itself, in one of its usual senses or frames — "
             "`stehen` meaning stand, be written or have a position are all "
             "`stehen`; `können` as a modal is `können`."),
    "false": ("A fixed expression with a meaning of its own — `ums Leben "
              "kommen` is not `das Leben`, `Bescheid wissen` is not `wissen` "
              "— or a different word: `gehört` from `hören` is not `gehören`, "
              "`gelassen` the adjective is not `lassen`."),
}

# Q9 of the corpus pass: the sentence teaches the word. `plain` says the
# sentence is the word; this says a reader who had every other word could
# work this one out. Labelled on 100 of the frame rows: 84 yes, 16 no.
QUESTION_GUESSABLE = (
    "Could a learner who knows every other word in `sentence` work out what "
    "`unit.spoken` means from this sentence alone?")
CRITERIA_GUESSABLE = {
    "true": ("The sentence gives the meaning away: `Ich brauche unbedingt eine "
             "gute Note.` for `brauchen`."),
    "false": ("The word could mean almost anything here: `Ich weiß nicht.` for "
              "`wissen`, `Das tun wir.` for `tun`."),
}

QUESTIONS = {"frame": (QUESTION, CRITERIA), "plain": (QUESTION_PLAIN, CRITERIA_PLAIN),
             "guessable": (QUESTION_GUESSABLE, CRITERIA_GUESSABLE),
             # the rubric form, from the pass's own question file
             "guessable_score": None}
GUESSABLE_LABELS = "04-pattern-sense-guessable-labels"


def guessable_labels() -> dict[str, str]:
    return {r["n"]: r["guessable"] for r in results.read(GUESSABLE_LABELS)}

# What B calls a good example, derived from the frame labels: `frame` and
# every `other` that is the same word in another sense or frame are good;
# `construction` and an `other` that is a different word are not.
# `(adjective` with the bracket: the note `klingen + adjective (sound)` names
# the verb's complement, and `gelassen (adjective, calm)` names the word.
_DIFFERENT_WORD = ("lemma error", "(adjective", "proper noun")


def plain_label(row: dict) -> str | None:
    if row["verdict"] == "frame":
        return "good"
    if row["verdict"] == "construction":
        return "bad"
    if row["verdict"] == "other":
        return "bad" if any(k in row["what"] for k in _DIFFERENT_WORD) else "good"
    return None


def _state(row: dict) -> dict:
    from deck.spoken import spoken                       # noqa: PLC0415
    return {
        "sentence": row["text"],
        "marked": row["surface"],
        "unit": {"canonical": row["pattern"], "spoken": spoken(row["pattern"])},
        "notation": NOTATION,
    }


def arm_jev(rows: list[dict], on_progress=None, asking: str = "frame") -> list[dict]:
    """One Noul per row against TypeSafe's Jev. Needs `TYPESAFE_API_KEY`."""
    import time                                          # noqa: PLC0415
    from typesafe_sdk import Noul, TypeSafeClient        # noqa: PLC0415
    from config import load_dotenv                       # noqa: PLC0415
    load_dotenv()
    out = []
    if asking == "guessable_score":
        from typesafe_sdk import Score                   # noqa: PLC0415
        from corpus.questions import GUESSABLE           # noqa: PLC0415
        question = {"frame": Score(
            instructions=GUESSABLE["instructions"].replace("units.{id}", "unit"),
            criteria=GUESSABLE["criteria"])}
        top = len(GUESSABLE["criteria"]) - 1
        read = lambda a: a.score / top            # noqa: E731 — expected level, 0..1
    else:
        instructions, criteria = QUESTIONS[asking]
        question = {"frame": Noul(instructions=instructions, criteria=criteria)}
        read = lambda a: a.noul                   # noqa: E731
    with TypeSafeClient() as client:
        for i, row in enumerate(rows, 1):
            started = time.time()
            response = client.system_one(_state(row), question)
            out.append({"n": row["n"], "p": round(read(response.answers["frame"]), 4),
                        "model": response.model,
                        "input_tokens": response.usage.input_tokens,
                        "seconds": round(time.time() - started, 2)})
            if on_progress and (i % 50 == 0 or i == len(rows)):
                on_progress(i, len(rows))
    return out


# The local endpoint's yes/no, as a probability. Probed 2026-09-20:
# `/v1/chat/completions` refuses `logprobs`; `/v1/completions` returns them
# and honours llama.cpp's `grammar`, reporting the distribution from before
# the grammar — which is the one wanted. The chat template is rendered by
# hand with the thinking block closed, since the model would otherwise spend
# its first tokens on `<think>`. The sampled text is never read: at
# temperature 0 it was not the argmax of what the server reported.
_TEMPLATE = ("<|im_start|>system\n{system}<|im_end|>\n"
             "<|im_start|>user\n{user}<|im_end|>\n"
             "<|im_start|>assistant\n<think>\n\n</think>\n\n")
_GRAMMAR = 'root ::= "yes" | "no"'


def _local_prompt(row: dict, asking: str = "frame") -> str:
    import json                                          # noqa: PLC0415
    state = _state(row)
    question, criteria = QUESTIONS[asking] or (None, None)
    return (f"State:\n{json.dumps(state, ensure_ascii=False, indent=1)}\n\n"
            f"Question: {question}\n"
            f"Yes means: {criteria['true']}\nNo means: {criteria['false']}\n"
            "Answer with one word, yes or no.")


def arm_local(rows: list[dict], on_progress=None, asking: str = "frame") -> list[dict]:
    import math, time                                    # noqa: PLC0415
    import requests                                      # noqa: PLC0415
    from config import load_dotenv                       # noqa: PLC0415
    from generation.client import LLMClient              # noqa: PLC0415
    load_dotenv()
    client = LLMClient()
    out = []
    for i, row in enumerate(rows, 1):
        prompt = _TEMPLATE.format(system="You judge German word senses. Answer yes or no.",
                                  user=_local_prompt(row, asking))
        body = {"model": client._model, "prompt": prompt, "max_tokens": 1,
                "temperature": 0, "logprobs": 10, "grammar": _GRAMMAR}
        started = time.time()
        # The endpoint is shared with whatever else is running against it,
        # and a saturated llama.cpp behind a tunnel answers 5xx rather than
        # queueing for ever — the same shape `deck.gloss._try` waits out.
        for attempt in range(4):
            response = requests.post(f"{client._base_url}/completions",
                                     headers=client._headers(), json=body, timeout=180)
            if response.status_code < 500 or attempt == 3:
                break
            time.sleep(5.0 * (attempt + 1))
        response.raise_for_status()
        first = response.json()["choices"][0]["logprobs"]["content"][0]
        # Every spelling of an answer is that answer: `Yes`, `yes`, ` yes`
        # and `Ja` all count for yes, and their probabilities add. Keeping
        # one per key let the last spelling reported win, which was ` yes`
        # at -8.3 while `Yes` sat at -0.6.
        mass = {"yes": 0.0, "no": 0.0}
        for t in first["top_logprobs"]:
            word = t["token"].strip().lower()
            if word in ("yes", "ja"):
                mass["yes"] += math.exp(t["logprob"])
            elif word in ("no", "nein"):
                mass["no"] += math.exp(t["logprob"])
        floor = math.exp(min(t["logprob"] for t in first["top_logprobs"]))
        yes = mass["yes"] or floor; no = mass["no"] or floor    # unseen: at most the floor
        out.append({"n": row["n"], "p": round(yes / (yes + no), 4),
                    "model": client._model, "input_tokens": "",
                    "seconds": round(time.time() - started, 2)})
        if on_progress and (i % 50 == 0 or i == len(rows)):
            on_progress(i, len(rows))
    return out


ARMS = {"jev": arm_jev, "local": arm_local}


def _arm_file(name: str, asking: str) -> str:
    return ARM.format(name) + ("" if asking == "frame" else f"-{asking}")


def run_arm(name: str, rows: list[dict], limit: int | None = None,
            asking: str = "frame") -> None:
    rows = rows[:limit] if limit else rows
    if asking == "plain":
        rows = [r for r in rows if plain_label(r) is not None]
    elif asking in ("guessable", "guessable_score"):
        labels = guessable_labels()
        rows = [r for r in rows if r["n"] in labels]
    answers = ARMS[name](rows, lambda i, n: print(f"  {name}: {i}/{n}", flush=True),
                         asking=asking)
    by_n = {r["n"]: r for r in rows}
    for a in answers:
        a["verdict"] = by_n[a["n"]]["verdict"]
        a["label"] = ("frame" if asking == "frame"
                      else plain_label(by_n[a["n"]]) if asking == "plain"
                      else guessable_labels()[a["n"]])       # both guessable forms
        a["rule"] = by_n[a["n"]].get("rule", "")
        a["stratum"] = by_n[a["n"]]["stratum"]
        a["pattern"] = by_n[a["n"]]["pattern"]
    results.write_detail(_arm_file(name, asking), answers)


def score_arm(name: str, asking: str = "frame") -> dict | None:
    """Precision and recall at 0.5, calibration at the ends, and the band."""
    answers = results.read(_arm_file(name, asking))
    if not answers:
        return None
    positive = {"frame": lambda a: a["verdict"] == "frame",
                "plain": lambda a: a.get("label") == "good",
                "guessable": lambda a: a.get("label") == "yes",
                "guessable_score": lambda a: a.get("label") == "yes"}[asking]
    def view(part):
        p = [(float(a["p"]), positive(a)) for a in part]
        yes = [f for prob, f in p if prob >= 0.5]
        frames = [prob for prob, f in p if f]
        sure_yes = [f for prob, f in p if prob >= 0.9]
        sure_no = [f for prob, f in p if prob <= 0.1]
        band = [f for prob, f in p if 0.3 < prob < 0.7]
        return {"rows": len(p),
                "precision": round(sum(yes) / max(len(yes), 1), 3),
                "recall": round(sum(1 for prob in frames if prob >= 0.5) / max(len(frames), 1), 3),
                "at_90": (len(sure_yes), sum(sure_yes)),
                "at_10": (len(sure_no), sum(1 for f in sure_no if not f)),
                "band": len(band)}
    residue = [a for a in answers if not a["rule"]]
    per_pattern: dict[str, list] = defaultdict(list)
    for a in answers:
        if a["stratum"] == "panel":
            per_pattern[a["pattern"]].append((float(a["p"]), a["verdict"]))
    tokens = sum(int(a["input_tokens"] or 0) for a in answers)
    return {"all": view(answers), "residue": view(residue), "per_pattern": per_pattern,
            "model": answers[0]["model"], "input_tokens": tokens,
            "seconds": round(sum(float(a["seconds"]) for a in answers), 1)}


def arm_section(name: str, asking: str = "frame") -> list[str]:
    s = score_arm(name, asking)
    if s is None:
        return []
    what = {"frame": "frame — does the sentence realise the blueprint",
            "plain": "plain — is this the word itself, not a fixed expression or another word",
            "guessable": "guessable — could a reader who had every other word work this one out",
            "guessable_score": "guessable as a rubric — nothing / a hint / gives it away, expected level scaled to 0–1"}[asking]
    lines = [f"## Arm: {name} ({s['model']}), question: {what}", ""]
    lines += [f"{s['all']['rows']} rows, {s['seconds']:.0f}s"
              + (f", {s['input_tokens']:,} input tokens" if s["input_tokens"] else "") + ".", "",
              "| view | rows | precision@0.5 | recall@0.5 | p ≥ 0.9: right/n | p ≤ 0.1: right/n | 0.3–0.7 band |",
              "|---|---|---|---|---|---|---|"]
    for label in ("all", "residue"):
        v = s[label]
        lines.append(f"| {label} | {v['rows']} | {v['precision']:.0%} | {v['recall']:.0%} | "
                     f"{v['at_90'][1]}/{v['at_90'][0]} | {v['at_10'][1]}/{v['at_10'][0]} | {v['band']} |")
    lines += ["", f"Precision and recall are of *{ {'frame': 'frame', 'plain': 'good example', 'guessable': 'guessable', 'guessable_score': 'guessable'}[asking] }* against everything else; "
              "the two calibration columns say, of the rows the judge was sure "
              "about, how many the label agreed with; the band is the rows it "
              "was not sure about, which is the number a person would still read.", "",
              "| pattern (panel) | p per row → label |", "|---|---|"]
    for pattern, rows in sorted(s["per_pattern"].items(), key=lambda kv: kv[0]):
        cells = ", ".join(f"{p:.2f}→{v[:5]}" for p, v in rows)
        lines.append(f"| `{pattern}` | {cells} |")
    lines.append("")
    return lines


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
        verdicts = Counter(r["verdict"] for r in rows)
        results.append(HISTORY, {
            "rows": len(rows), "frame": verdicts["frame"], "other": verdicts["other"],
            "construction": verdicts["construction"], "unclear": verdicts["unclear"],
            "rule_tagged": sum(1 for r in rows if r["rule"]),
            **{k: effect[k] for k in ("sentences", "verb_pattern_rows", "refused",
                                      "aux", "modal", "rerouted", "share_refused")},
        })
        write_report(rows, effect)
    elif what == "arm":
        name = sys.argv[2] if len(sys.argv) > 2 else ""
        if name not in ARMS:
            raise SystemExit("usage: pattern_sense.py arm jev|local [limit]")
        rows = judged()
        if not rows or "rule" not in rows[0]:
            raise SystemExit("run `measure` first: the arms are scored against the judged file")
        extra = sys.argv[3:]
        asking = next((a for a in ("plain", "guessable_score", "guessable") if a in extra), "frame")
        limit = next((int(x) for x in extra if x.isdigit()), None)
        run_arm(name, rows, limit, asking)
        write_report(rows, _last_effect())
    else:
        raise SystemExit("usage: pattern_sense.py [sample|measure|arm jev|local [plain] [limit]]")


if __name__ == "__main__":
    main()
